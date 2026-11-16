"""db_review 文件上传：脚本(.sql，固定后缀 + 方言校验) / 回滚演练记录(.pdf)。"""

from __future__ import annotations

import hashlib
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, UploadFile

from backend.common.response import success
from backend.data.dao.business.file_dao import FileDao
from backend.middleware.auth import CurrentUser, get_current_user
from backend.observability.exception import BizException, ErrCode
from backend.security.rbac import Scope
from backend.security.security import require_scope
from backend.services.sql_script_service import ensure_sql_filename, validate_script

router = APIRouter(prefix="/db-review", tags=["tenant"])

_MAX_MB = 20


@router.post("/upload", summary="上传评审脚本/演练记录")
async def upload_review_file(
    file: UploadFile = File(...),  # noqa: B008
    kind: str = Form(...),  # noqa: B008  script | drill
    db_type: Optional[str] = Form(None),  # noqa: B008
    request_id: Optional[int] = Form(None),  # noqa: B008
    thread_id: Optional[str] = Form(None),  # noqa: B008
    current: CurrentUser = Depends(get_current_user),
    _: object = Depends(require_scope(Scope.UNIFIED_ASK)),
):
    data = await file.read()
    if len(data) > _MAX_MB * 1024 * 1024:
        raise BizException(ErrCode.PARAM_ERROR, f"文件超过 {_MAX_MB}MB")

    original = file.filename or "upload"
    if kind == "script":
        try:
            text = data.decode("utf-8")
        except Exception as exc:  # noqa: BLE001
            raise BizException(ErrCode.PARAM_ERROR, "脚本文件需为 UTF-8 文本") from exc
        check = validate_script(text, db_type or "")
        if not check.get("ok"):
            raise BizException(ErrCode.PARAM_ERROR, "；".join(check.get("errors") or ["脚本不合法"]))
        filename = ensure_sql_filename(original)
        ext = ".sql"
        content_type = "text/plain"
    elif kind == "drill":
        if not original.lower().endswith(".pdf"):
            raise BizException(ErrCode.PARAM_ERROR, "回滚演练记录须为 PDF")
        filename = original
        ext = ".pdf"
        content_type = "application/pdf"
    else:
        raise BizException(ErrCode.PARAM_ERROR, "kind 仅支持 script/drill")

    checksum = hashlib.sha256(data).hexdigest()
    res = await FileDao.save_new_version(
        tenant_id=current.tenant_id,
        uploader_user_id=current.user_id,
        original_name=filename,
        data=data,
        file_size=len(data),
        content_type=content_type,
        file_ext=ext,
        checksum=checksum,
        remark=f"db_review_{kind}",
        agent_type="db_review",
        file_kind=kind,
        thread_id=thread_id,
        request_id=request_id,
        db_type=db_type,
        file_type="db_review",
        subtype=kind,
    )
    row = res.get("row") or res.get("latest")
    if row is None:
        raise BizException(ErrCode.PARAM_ERROR, "文件元数据写入失败")
    return success(
        {
            "file_id": row["id"],
            "file_uuid": row["file_uuid"],
            "object_key": row["object_key"],
            "kind": kind,
        }
    )
