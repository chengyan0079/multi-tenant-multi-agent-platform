"""文件管理端点：分页 / 详情 / 上传（MinIO） / 下载（MinIO）。

挂在 /api/v1/admin/files 下，但**不挂整组 require_super_admin**（见 api/router.py）：
文件按租户开放给所有持相应 scope 的用户，端点各自 `require_scope`。

隔离规则：
- 普通用户 / 租户管理员：只能看、只能下载本租户文件（tenant_id = current.tenant_id）；
- 平台超管（tenant_id=None）：可查全部、可按 tenant_id 过滤；自己上传的文件记平台级（tenant_id=NULL）。
"""
from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from backend.common.response import success
from backend.config import config
from backend.data.clients.minio import get_storage
from backend.data.dao.business.file_dao import FileDao
from backend.broker.publish import enqueue_task
from backend.broker.types import TaskType
from backend.middleware.auth import CurrentUser, get_current_user
from backend.observability.exception import BizException, ErrCode
from backend.security.rbac import Scope
from backend.security.security import require_scope

router = APIRouter(prefix="/files", tags=["admin"])

def _max_upload_bytes() -> int:
    """单文件大小上限（字节），由 FILE_MAX_UPLOAD_MB 配置，最小 1MB。"""
    return max(1, config.file.max_upload_mb) * 1024 * 1024


# 允许上传的扩展名 → MIME 类型（PDF / Markdown / TXT）
_ALLOWED_EXTS: dict[str, str] = {
    ".pdf": "application/pdf",
    ".md": "text/markdown",
    ".txt": "text/plain",
}


def _serialize(row: dict) -> dict:
    """对外视图：不含 object_key / bucket 等存储实现细节。"""
    return {
        "id": row["id"],
        "tenant_id": row["tenant_id"],
        "uploader_user_id": row["uploader_user_id"],
        "original_name": row.get("original_name"),
        "file_name": row["file_name"],
        "file_size": row["file_size"],
        "content_type": row["content_type"],
        "file_ext": row["file_ext"],
        "file_version": row["file_version"],
        "version_count": row.get("version_count"),
        "checksum": row["checksum"],
        "remark": row["remark"],
        "parse_status": row.get("parse_status") or "pending",
        "create_at": row["create_at"],
        "updated_at": row["updated_at"],
    }


def _visible(row: dict, current: CurrentUser) -> bool:
    """超管全量可见；其余只能看本租户（tenant_id 为 NULL 的平台文件仅超管可见）。"""
    return current.is_super_admin or row["tenant_id"] == current.tenant_id


@router.get("", summary="文件列表（分页）")
async def list_files(
    file_name: Optional[str] = Query(None, description="按文件名模糊搜索"),
    tenant_id: Optional[int] = Query(None, description="超管可按租户筛选；其他角色忽略"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    current: CurrentUser = Depends(get_current_user),  # noqa: B008
    _: object = Depends(require_scope(Scope.FILE_PAGE)),  # noqa: B008
):
    # 非超管强制收敛到本租户，忽略前端传的 tenant_id
    scope_tenant = tenant_id if current.is_super_admin else current.tenant_id
    rows, total = await FileDao.list_latest(
        tenant_id=scope_tenant, keyword=file_name, page=page, page_size=page_size
    )
    return success(
        {
            "items": [_serialize(r) for r in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    )


@router.get("/config", summary="文件上传配置")
async def file_config(
    _: object = Depends(require_scope(Scope.FILE_PAGE)),  # noqa: B008
):
    """返回前端所需的上传限制（单文件上限 MB）。"""
    return success({"max_upload_mb": config.file.max_upload_mb})


async def _process_one_upload(
    file: UploadFile, current: CurrentUser, remark: str | None
) -> dict[str, Any]:
    """单个文件校验 → 去重判定 → 落库；返回 _serialize 后的视图。

    校验失败 / 重复上传会被转换为 BizException，由调用方决定是否向上抛出（批量接口会捕获并计入失败项）。
    """
    filename = file.filename or ""
    ext = Path(filename).suffix.lower()
    if ext not in _ALLOWED_EXTS:
        raise BizException(
            ErrCode.PARAM_ERROR,
            "仅支持上传 PDF / Markdown / TXT（.pdf / .md / .txt）文件",
        )

    data = await file.read()
    if not data:
        raise BizException(ErrCode.PARAM_ERROR, "文件为空")
    if len(data) > _max_upload_bytes():
        raise BizException(
            ErrCode.PARAM_ERROR, f"文件超过 {config.file.max_upload_mb}MB 上限"
        )

    tenant_id = current.tenant_id  # 超管为 None → 平台级
    checksum = hashlib.sha256(data).hexdigest()
    content_type = _ALLOWED_EXTS[ext]

    # 方案 B：同名（lower(trim) 归一化）视为同一文件；
    #   - 内容与最新版一致 → 拦截（不落库）；
    #   - 否则版本 +1、沿用同一 file_uuid；不同名 → 新文件。
    result = await FileDao.save_new_version(
        tenant_id=tenant_id,
        uploader_user_id=current.user_id,
        original_name=filename,
        data=data,
        file_size=len(data),
        content_type=content_type,
        file_ext=ext,
        checksum=checksum,
        remark=remark,
    )
    if result.get("blocked"):
        latest_id = result["latest"]["id"]
        raise BizException(
            ErrCode.PARAM_ERROR,
            f"该文件已上传过（内容与最新版本一致），无需重复上传；最新版本ID：{latest_id}",
        )
    return _serialize(result["row"])


@router.post("/upload", summary="上传文件（MinIO）")
async def upload_file(
    file: UploadFile = File(...),  # noqa: B008
    remark: Optional[str] = Form(None),  # noqa: B008
    current: CurrentUser = Depends(get_current_user),  # noqa: B008
    _: object = Depends(require_scope(Scope.FILE_UPLOAD)),  # noqa: B008
):
    return success(await _process_one_upload(file, current, remark))


@router.post("/batch-upload", summary="批量上传文件（MinIO）")
async def batch_upload_files(
    files: list[UploadFile] = File(...),  # noqa: B008
    remark: Optional[str] = Form(None),  # noqa: B008
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    current: CurrentUser = Depends(get_current_user),  # noqa: B008
    _: object = Depends(require_scope(Scope.FILE_UPLOAD)),  # noqa: B008
) -> Any:
    results: list[dict[str, Any]] = []
    for f in files:
        try:
            results.append({"ok": True, **await _process_one_upload(f, current, remark)})
        except BizException as e:
            results.append({"original_name": f.filename or "", "ok": False, "error": e.detail})
        except Exception as e:  # noqa: BLE001
            results.append({"original_name": f.filename or "", "ok": False, "error": str(e)})

    # todo 数据源为本次上传的内存结果而非 DB 查询，此处无法走 fetch_page
    total = len(results)
    start = (page - 1) * page_size
    return success({
        "count": total,
        "items": results[start:start + page_size],
        "total": total,
        "page": page,
        "page_size": page_size,
    })


class ParseRequest(BaseModel):
    """触发解析的请求体：选中的文件 id 列表。"""
    file_ids: list[int]


@router.post("/parse", summary="触发文档解析（向量化入 Milvus，走消息队列）")
async def parse_files(
    body: ParseRequest,
    current: CurrentUser = Depends(get_current_user),  # noqa: B008
    _: object = Depends(require_scope(Scope.FILE_UPLOAD)),  # noqa: B008
):
    """把选中的文件提交到消息队列做解析向量化。

    仅处理当前用户可见的文件（越权/不存在的 id 忽略）；提交成功先把状态置 parsing，
    真正的「MinIO 取文件 → 切分 → BGE-M3 向量化（稠密+稀疏）→ 写 Milvus」由消费者完成。
    """
    if not body.file_ids:
        raise BizException(ErrCode.PARAM_ERROR, "file_ids 不能为空")
    rows = await FileDao.get_many([int(x) for x in body.file_ids])
    visible = [r for r in rows if _visible(r, current)]
    if not visible:
        raise BizException(ErrCode.PARAM_ERROR, "没有可解析的文件（不存在或无权限）")
    ids = [r["id"] for r in visible]
    await FileDao.set_parse_status(ids, "parsing", tenant_id=current.tenant_id)
    for r in visible:
        await enqueue_task(
            TaskType.DOC_PARSE,
            tenant_id=current.tenant_id,
            user_id=current.user_id,
            data={
                "file_id": r["id"],
                "object_key": r["object_key"],
                "bucket": r["bucket"],
                "tenant_id": current.tenant_id,
                "file_ext": r["file_ext"],
            },
        )
    return success({"queued": len(ids)})


@router.get("/{file_id}", summary="文件详情")
async def get_file(
    file_id: int,
    current: CurrentUser = Depends(get_current_user),  # noqa: B008
    _: object = Depends(require_scope(Scope.FILE_VIEW)),  # noqa: B008
):
    row = await FileDao.get(file_id)
    if row is None or not _visible(row, current):
        raise BizException(ErrCode.NOT_FOUND, f"文件不存在: {file_id}")
    versions = await FileDao.list_versions(row["file_uuid"])
    return success({**_serialize(row), "versions": [_serialize(v) for v in versions]})


@router.get("/{file_id}/download", summary="下载文件（MinIO）")
async def download_file(
    file_id: int,
    current: CurrentUser = Depends(get_current_user),  # noqa: B008
    _: object = Depends(require_scope(Scope.FILE_DOWNLOAD)),  # noqa: B008
):
    row = await FileDao.get(file_id)
    if row is None or not _visible(row, current):
        raise BizException(ErrCode.NOT_FOUND, f"文件不存在: {file_id}")

    # 历史版本不允许下载（只能下最新版）
    max_v = await FileDao.max_version(row["file_uuid"])
    if max_v is not None and int(row["file_version"]) != int(max_v):
        raise BizException(ErrCode.PARAM_ERROR, "历史版本不允许下载，只能下载最新版")

    storage = await get_storage()
    try:
        data = await asyncio.to_thread(storage.get_bytes, row["object_key"])
    except Exception as exc:  # noqa: BLE001 - 对象丢失/存储异常统一按 404 提示
        raise BizException(ErrCode.NOT_FOUND, f"文件对象已丢失或不可读: {exc}")  # noqa: B904

    filename = quote(row["file_name"])
    headers = {"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"}
    return Response(
        content=data,
        media_type=row["content_type"] or "application/octet-stream",
        headers=headers,
    )
