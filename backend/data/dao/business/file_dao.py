"""文件元数据 DAO：`agent_file`（单表版本化）。"""
# todo 版本化判定与 pg_advisory_xact_lock 并发控制见 upload 方法，改动前先读其事务边界。
from __future__ import annotations

import asyncio
import hashlib
from typing import Any
import uuid6

from sqlalchemy import text

from backend.data.clients.minio import build_object_key, get_storage
from backend.data.sql import fetch_all, fetch_one, fetch_page, fetch_value, session_scope
from backend.data.sql.audit import audit_on_insert

# 写入列白名单：调用方传什么就写什么，多余字段丢弃（防拼错列名）
_INSERT_COLUMNS = (
    "tenant_id",
    "uploader_user_id",
    "original_name",
    "file_uuid",
    "file_name",
    "object_key",
    "bucket",
    "file_size",
    "content_type",
    "file_ext",
    "file_version",
    "checksum",
    "remark",
)

_INSERT = text(f"""
INSERT INTO agent_file (
    {", ".join(_INSERT_COLUMNS)},
    create_user_id, update_user_id, create_tenant_id, update_tenant_id
) VALUES (
    {", ".join(":" + c for c in _INSERT_COLUMNS)},
    :create_user_id, :update_user_id, :create_tenant_id, :update_tenant_id
)
RETURNING *
""")

_SELECT_ONE = text("SELECT * FROM agent_file WHERE id = :id")


def _build_filters(*, tenant_id: int | None, keyword: str | None) -> tuple[str, dict[str, Any]]:
    """拼 WHERE：列名写死、值走绑定参数。tenant_id=None 表示不过滤（超管全量）。

    搜索按 `original_name` 模糊匹配（重命名后的 file_name 无业务含义，不检索）。
    """
    conditions: list[str] = []
    params: dict[str, Any] = {}
    if tenant_id is not None:
        conditions.append("tenant_id = :tenant_id")
        params["tenant_id"] = tenant_id
    if keyword:
        conditions.append("original_name ILIKE :kw")
        params["kw"] = f"%{keyword}%"
    where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
    return where, params


def _advisory_key(tenant_id: int | None, user_id: int, norm: str) -> int:
    """把 (tenant, user, 归一化名) 映射成 63 位正整数锁键（落进 bigint 正区间）。"""
    raw = f"{tenant_id}:{user_id}:{norm}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(raw).digest()[:8], "big") & 0x7FFFFFFFFFFFFFFF


def _latest_by_name_stmt(tenant_id: int | None) -> tuple[Any, dict[str, Any]]:
    """取某 (租户, 用户, 归一化名) 下 file_version 最大的一行。"""
    params: dict[str, Any] = {}
    if tenant_id is None:
        tenant_cond = "tenant_id IS NULL AND "
    else:
        tenant_cond = "tenant_id = :tid AND "
        params["tid"] = tenant_id
    stmt = text(
        f"SELECT * FROM agent_file WHERE {tenant_cond}"
        "uploader_user_id = :uid AND lower(trim(original_name)) = :norm "
        "ORDER BY file_version DESC, id DESC LIMIT 1"
    )
    return stmt, params


class FileDao:
    """文件元数据读写。"""

    @staticmethod
    async def list_latest(
        *,
        tenant_id: int | None = None,
        keyword: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        """列表：一个逻辑文件一条，只取最新版。返回 (最新版行, 逻辑文件总数)。

        最新版用 `DISTINCT ON (file_uuid) ... ORDER BY file_uuid, file_version DESC` 取；
        `version_count` 为该文件的总版本数；`total` 用 `count(DISTINCT file_uuid)`。
        """
        where, params = _build_filters(tenant_id=tenant_id, keyword=keyword)
        inner = (
            f"SELECT DISTINCT ON (file_uuid) * FROM agent_file{where}"
            " ORDER BY file_uuid, file_version DESC"
        )
        count_sql = f"SELECT count(DISTINCT file_uuid) FROM agent_file{where}"
        list_sql = (
            "SELECT t.*, (SELECT count(*) FROM agent_file f2 WHERE f2.file_uuid = t.file_uuid)"
            " AS version_count"
            f" FROM ({inner}) t"
            " ORDER BY t.create_at DESC, t.id DESC LIMIT :limit OFFSET :offset"
        )
        async with session_scope() as session:
            return await fetch_page(
                session, text(list_sql), text(count_sql), params,
                page=page, page_size=page_size,
            )

    @staticmethod
    async def get(file_id: int) -> dict[str, Any] | None:
        """按 id 取单行，不存在返回 None。"""
        async with session_scope() as session:
            return await fetch_one(session, _SELECT_ONE, {"id": file_id})

    @staticmethod
    async def list_versions(file_uuid: str) -> list[dict[str, Any]]:
        """某逻辑文件的全部版本（倒序），供详情查看版本历史。"""
        async with session_scope() as session:
            return await fetch_all(
                session,
                text(
                    "SELECT * FROM agent_file WHERE file_uuid = :uuid"
                    " ORDER BY file_version DESC, id DESC"
                ),
                {"uuid": file_uuid},
            )

    @staticmethod
    async def max_version(file_uuid: str) -> int | None:
        """某逻辑文件的最大版本号（下载时用于判断是否为最新版）。"""
        async with session_scope() as session:
            return await fetch_value(
                session,
                text("SELECT max(file_version) FROM agent_file WHERE file_uuid = :uuid"),
                {"uuid": file_uuid},
            )

    @staticmethod
    async def get_many(file_ids: list[int]) -> list[dict[str, Any]]:
        """按 id 列表批量取行（用于解析前校验可见性）。"""
        if not file_ids:
            return []
        async with session_scope() as session:
            return await fetch_all(
                session,
                text("SELECT * FROM agent_file WHERE id = ANY(:ids)"),
                {"ids": tuple(file_ids)},
            )

    @staticmethod
    async def set_parse_status(
        file_ids: list[int], status: str, *, tenant_id: int | None = None
    ) -> int:
        """批量更新解析状态（触发解析置 parsing；消费完成置 parsed/failed）。

        file_ids 已由调用方按可见性过滤；tenant_id 非 None 时额外加租户约束（超管传 None 不过滤）。
        """
        if not file_ids:
            return 0
        params: dict[str, Any] = {"status": status, "ids": tuple(file_ids)}
        where = "id = ANY(:ids)"
        if tenant_id is not None:
            where = f"({where}) AND tenant_id = :tid"
            params["tid"] = tenant_id
        stmt = text(f"UPDATE agent_file SET parse_status = :status WHERE {where}")
        async with session_scope() as session:
            res = await session.execute(stmt, params)
            return int(res.rowcount)

    @staticmethod
    async def save_new_version(
        *,
        tenant_id: int | None,
        uploader_user_id: int,
        original_name: str,
        data: bytes,
        file_size: int,
        content_type: str | None,
        file_ext: str | None,
        checksum: str,
        remark: str | None,
    ) -> dict[str, Any]:
        """上传落库（方案 B 判定 + 串行写入）。

        返回：
        - {"blocked": True, "latest": <最新版行>}  → 内容与最新版一致，调用方应报错拦截；
        - {"row": <新插入行>}                        → 已落库（新版本或新文件）。
        """
        norm = (original_name or "").strip().lower()
        lock_key = _advisory_key(tenant_id, uploader_user_id, norm)
        async with session_scope() as session:
            # 同一 (租户, 用户, 归一化名) 串行，避免并发算出同一版本号
            await session.execute(
                text("SELECT pg_advisory_xact_lock(:k)"), {"k": lock_key}
            )

            latest_stmt, latest_params = _latest_by_name_stmt(tenant_id)
            latest_params.update(uid=uploader_user_id, norm=norm)
            latest = await fetch_one(session, latest_stmt, latest_params)

            # 与最新版内容一致 → 拦截（不落库）
            if latest is not None and latest["checksum"] == checksum:
                return {"blocked": True, "latest": latest}

            version = (int(latest["file_version"]) + 1) if latest is not None else 1
            file_uuid = latest["file_uuid"] if latest is not None else uuid6.uuid7().hex

            # 重命名：{file_uuid}_{user_id}_v{版本号}_upload{扩展名}
            stored_name = f"{file_uuid}_{uploader_user_id}_v{version}_upload{file_ext}"
            tenant_seg = f"t{tenant_id}" if tenant_id is not None else "system"
            object_key = build_object_key(
                filetype="files",
                tenant_id=tenant_seg,
                user_id=uploader_user_id,
                name=f"{file_uuid}_v{version}",
                ext=(file_ext or "").lstrip(".") or "bin",
            )

            # 上传 MinIO（在锁/事务内，保证串行；失败则整体回滚）
            storage = await get_storage()
            await asyncio.to_thread(
                storage.put_bytes, object_key, data, content_type=content_type
            )

            params: dict[str, Any] = {
                "tenant_id": tenant_id,
                "uploader_user_id": uploader_user_id,
                "original_name": original_name,
                "file_uuid": file_uuid,
                "file_name": stored_name,
                "object_key": object_key,
                "bucket": storage.bucket,
                "file_size": file_size,
                "content_type": content_type,
                "file_ext": file_ext,
                "file_version": version,
                "checksum": checksum,
                "remark": remark,
            }
            params.update(audit_on_insert(tenant_id=tenant_id))
            row = await fetch_one(session, _INSERT, params)
        if row is None:  # RETURNING * 正常不会为空
            raise RuntimeError("文件元数据写入失败：未返回插入行")
        return {"row": row}
