"""文件管理端点：分页 / 详情 / 上传（MinIO） / 下载（MinIO）。

挂在 /api/v1/tenant/agent/files 下（业务域 _BUSINESS），整组 require_tenant()：
仅租户用户可访问（超管无租户，调用直接 403），端点各自 `require_scope(qa_file:*)`。

隔离规则：所有操作强制收敛到 current.tenant_id，忽略前端传入的 tenant_id，杜绝跨租户。
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

from backend.common.logger import logger
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

router = APIRouter(prefix="/agent/files", tags=["agent-files"])

def _max_upload_bytes() -> int:
    """单文件大小上限（字节），由 QA_MAX_UPLOAD_MB 配置，最小 1MB。"""
    return max(1, config.qa.max_upload_mb) * 1024 * 1024


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
    """仅本租户文件可见；租户用户无跨租户查看能力。"""
    return row["tenant_id"] == current.tenant_id


@router.get("", summary="文件列表（分页）")
async def list_files(
    file_name: Optional[str] = Query(None, description="按文件名模糊搜索"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    current: CurrentUser = Depends(get_current_user),  # noqa: B008
    _: object = Depends(require_scope(Scope.QA_FILE_PAGE)),  # noqa: B008
):
    # 固定本租户，忽略前端可能传入的 tenant_id
    rows, total = await FileDao.list_latest(
        tenant_id=_tenant_id(current), keyword=file_name, page=page, page_size=page_size
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
    _: object = Depends(require_scope(Scope.QA_FILE_PAGE)),  # noqa: B008
):
    """返回前端所需的上传限制与上传后行为。"""
    return success({
        "max_upload_mb": config.qa.max_upload_mb,
        "auto_parse": config.qa.auto_parse,
    })


async def _enqueue_parse(row: dict, current: CurrentUser) -> str | None:
    """上传成功后自动触发解析：先置 parsing，再写 Outbox。

    返回消息 key；写 Outbox 失败返回 None，此时回退状态为 pending（不阻断上传，
    用户仍可在文件列表手动点「解析」重试）。

    入队 tenant_id 用文件归属租户（row["tenant_id"]），而非 current.tenant_id，
    保证消费端严格按租户 id 校验时与落库口径一致，且租户隔离不被 current 视角破坏。
    """
    file_id = row["id"]
    file_tenant = row.get("tenant_id")
    try:
        await FileDao.set_parse_status([file_id], "parsing", tenant_id=file_tenant)
    except Exception as exc:  # noqa: BLE001 - 状态更新失败不应让上传（已成功）被判失败
        logger.warning(f"上传后置 parsing 失败 file_id={file_id}：{exc}")

    key: str | None = None
    try:
        key = await enqueue_task(
            TaskType.QA_PARSE,
            tenant_id=file_tenant,
            user_id=current.user_id,
            data={
                "file_id": file_id,
                "object_key": row["object_key"],
                "bucket": row["bucket"],
                "tenant_id": file_tenant,
                "file_ext": row["file_ext"],
                # 透传原始文件名：Milvus 的 file_name/source_location 用它，避免展示成 {uuid}_v1.pdf
                "file_name": row.get("original_name") or row.get("file_name"),
            },
        )
    except Exception as exc:  # noqa: BLE001 - 入队异常同样不阻断上传
        logger.error(f"上传后自动解析入队异常 file_id={file_id}：{exc}")

    if key is None:
        try:
            await FileDao.set_parse_status([file_id], "pending", tenant_id=file_tenant)
        except Exception as exc:  # noqa: BLE001 - 回退失败只记录，不影响上传结果
            logger.warning(f"回退 pending 失败 file_id={file_id}：{exc}")
        logger.warning(f"上传后自动解析入队失败 file_id={file_id}，请手动触发解析")
    return key


def _tenant_id(current: CurrentUser) -> int:
    """本次操作的租户 id：固定取 current.tenant_id，不接受外部指定，杜绝跨租户。"""
    if current.tenant_id is None:
        raise BizException(ErrCode.PARAM_ERROR, "当前账号无租户归属，无法操作文件")
    return current.tenant_id


async def _process_one_upload(
    file: UploadFile, current: CurrentUser, remark: str | None
) -> dict[str, Any]:
    """单个文件校验 → 去重判定 → 落库 →（可选）自动入队解析；返回 _serialize 后的视图。

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
            ErrCode.PARAM_ERROR, f"文件超过 {config.qa.max_upload_mb}MB 上限"
        )

    tid = _tenant_id(current)
    checksum = hashlib.sha256(data).hexdigest()
    content_type = _ALLOWED_EXTS[ext]

    # 方案 B：同名（lower(trim) 归一化）视为同一文件；
    #   - 内容与最新版一致 → 拦截（不落库）；
    #   - 否则版本 +1、沿用同一 file_uuid；不同名 → 新文件。
    result = await FileDao.save_new_version(
        tenant_id=tid,
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

    row = result["row"]
    view = _serialize(row)
    if config.qa.auto_parse:
        # 上传即解析：入队 qa.parse，消费端写入 Milvus 后回写 parse_status=parsed
        view["parse_queued"] = await _enqueue_parse(row, current) is not None
    else:
        view["parse_queued"] = False
    return view


@router.post("/upload", summary="上传文件（MinIO）")
async def upload_file(
    file: UploadFile = File(...),  # noqa: B008
    remark: Optional[str] = Form(None),  # noqa: B008
    current: CurrentUser = Depends(get_current_user),  # noqa: B008
    _: object = Depends(require_scope(Scope.QA_FILE_UPLOAD)),  # noqa: B008
):
    return success(await _process_one_upload(file, current, remark))


@router.post("/batch-upload", summary="批量上传文件（MinIO）")
async def batch_upload_files(
    files: list[UploadFile] = File(...),  # noqa: B008
    remark: Optional[str] = Form(None),  # noqa: B008
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    current: CurrentUser = Depends(get_current_user),  # noqa: B008
    _: object = Depends(require_scope(Scope.QA_FILE_UPLOAD)),  # noqa: B008
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
    _: object = Depends(require_scope(Scope.QA_FILE_UPLOAD)),  # noqa: B008
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
    await FileDao.set_parse_status(ids, "parsing", tenant_id=_tenant_id(current))

    queued, failed = 0, []
    for r in visible:
        key = await enqueue_task(
            TaskType.QA_PARSE,
            tenant_id=r["tenant_id"],
            user_id=current.user_id,
            data={
                "file_id": r["id"],
                "object_key": r["object_key"],
                "bucket": r["bucket"],
                "tenant_id": r["tenant_id"],
                "file_ext": r["file_ext"],
                "file_name": r.get("original_name") or r.get("file_name"),
            },
        )
        if key is None:
            # 写 Outbox 失败：不能留在 parsing，否则永远等不到消费
            failed.append(r["id"])
        else:
            queued += 1

    if failed:
        await FileDao.set_parse_status(failed, "pending", tenant_id=_tenant_id(current))
        logger.warning(f"解析入队失败 {len(failed)} 个文件，已回退 pending: {failed}")
    return success({"queued": queued, "failed": failed})


@router.get("/{file_id}", summary="文件详情")
async def get_file(
    file_id: int,
    current: CurrentUser = Depends(get_current_user),  # noqa: B008
    _: object = Depends(require_scope(Scope.QA_FILE_VIEW)),  # noqa: B008
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
    _: object = Depends(require_scope(Scope.QA_FILE_DOWNLOAD)),  # noqa: B008
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

    # 用原始文件名下载：file_name 是含 uuid/版本的存储名，直接给用户会变成 a1b2...v1.pdf
    filename = quote(row.get("original_name") or row["file_name"])
    headers = {"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"}
    return Response(
        content=data,
        media_type=row["content_type"] or "application/octet-stream",
        headers=headers,
    )
