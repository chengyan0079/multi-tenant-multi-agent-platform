"""统一附件服务：两阶段上传第一步（存文件 + 记引用，不建业务行、不入会话）。"""
from __future__ import annotations

import hashlib
import os

from fastapi import UploadFile

from backend.api.v1.tenant.agent.unified_dtos import AttachmentUploadResponse
from backend.config import config
from backend.data.dao.business.file_dao import FileDao

# 缺省允许类型：覆盖 4 个 Agent 的入口文件（试卷 docx / 简历 pdf / 通用文本图片）
_DEFAULT_EXTS = {".docx", ".pdf", ".txt", ".md", ".csv", ".json", ".png", ".jpg", ".jpeg"}


class AttachmentError(ValueError):
    """附件校验/存储失败，端点层转为 400/413。"""


async def upload_attachment(
    *,
    file: UploadFile,
    tenant_id: int,
    user_id: int,
    accept_exts: list[str] | None = None,
    max_mb: int | None = None,
) -> AttachmentUploadResponse:
    """上传一个附件，返回可后续引用的 file_ref。

    accept_exts 来自 spec.accept_files；为空时退回默认白名单。大小上限取 max_mb 或
    config.qa.max_upload_mb。内容空 / 类型不符 / 超限均抛 AttachmentError。
    """
    filename = file.filename or ""
    ext = os.path.splitext(filename)[1].lower()
    allowed = _normalize_exts(accept_exts) if accept_exts else _DEFAULT_EXTS
    if ext not in allowed:
        raise AttachmentError(f"不支持的文件类型：{ext or '无扩展名'}，允许：{sorted(allowed)}")

    data = await file.read()
    if not data:
        raise AttachmentError("空文件")
    limit = max_mb or config.qa.max_upload_mb
    if len(data) > limit * 1024 * 1024:
        raise AttachmentError(f"文件超过 {limit}MB 上限")

    content_type = file.content_type or "application/octet-stream"
    checksum = hashlib.sha256(data).hexdigest()
    res = await FileDao.save_new_version(
        tenant_id=tenant_id,
        uploader_user_id=user_id,
        original_name=filename,
        data=data,
        file_size=len(data),
        content_type=content_type,
        file_ext=ext,
        checksum=checksum,
        remark="unified_attachment",
        agent_type="unified",
        file_kind="attachment",
    )
    # 与最新版内容一致时被拦截（不重复落库），仍返回已有引用
    row = res.get("row") or res.get("latest")
    if row is None:
        raise AttachmentError("文件元数据写入失败")
    return AttachmentUploadResponse(
        file_ref=str(row["id"]),
        filename=filename,
        size=len(data),
        content_type=content_type,
    )


async def get_attachment_object_key(file_ref: str) -> str | None:
    """由 file_ref（agent_file 行 id）取 MinIO 对象 key，供任务型建业务行时引用。"""
    try:
        row = await FileDao.get(int(file_ref))
    except (TypeError, ValueError):
        return None
    if not row:
        return None
    return row.get("object_key")


def _normalize_exts(exts: list[str]) -> set[str]:
    """归一化扩展名集合（统一小写并补前导点）。"""
    out: set[str] = set()
    for e in exts:
        e = e.strip().lower()
        if not e:
            continue
        out.add(e if e.startswith(".") else f".{e}")
    return out
