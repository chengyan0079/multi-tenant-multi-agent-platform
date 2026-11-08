"""
api - 简历审查 API

挂在 /api/v1/tenant/resume（由 api/router.py 以 require_tenant() 挂载）。
上传 -> 直接存 MinIO -> 写骨架行(status=processing, 含审计列) -> 发 resume.review 消息 -> 消费者经 Orchestrator 异步跑 LangGraph -> 节点回写结果。
查询/删除/列表均按 tenant_id + user_id 做数据隔离。

Author: 骆昊
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import uuid6
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import text

from backend.broker.publish import enqueue_task
from backend.broker.types import TaskType
from backend.common.logger import get_logger
from backend.common.response import success
from backend.config import config
from backend.data.clients.minio import build_object_key, get_storage
from backend.data.sql import fetch_page, session_scope
from backend.middleware.auth import CurrentUser, get_current_user
from backend.security.rbac import Scope
from backend.security.security import require_scope

logger = get_logger("resume_api")

router = APIRouter(prefix="/resume", tags=["resume"])

# 业务约束（MAX_PDF_SIZE 来自 config.qa.max_upload_mb；REVIEW_TIMEOUT 来自 config.scheduler.resume_timeout_min）
ALLOWED_EXT = {".pdf"}

_LIST_REVIEWS = text("""
SELECT id, status, weighted_score, pdf_minio_path, create_at, updated_at
FROM agent_resume_reviews
WHERE tenant_id = :tenant_id AND user_id = :user_id
ORDER BY create_at DESC
LIMIT :limit OFFSET :offset
""")
_COUNT_REVIEWS = text("""
SELECT count(*) FROM agent_resume_reviews
WHERE tenant_id = :tenant_id AND user_id = :user_id
""")


async def _mark_review_failed(review_id: str, error_msg: str) -> None:
    """将评审记录标记为失败（仅当仍处于 processing 时）。"""
    try:
        async with session_scope() as session:
            await session.execute(
                text(
                    "UPDATE agent_resume_reviews "
                    "SET status = 'failed', error_msg = :error_msg "
                    "WHERE id = :review_id AND status = 'processing'"
                ),
                {"error_msg": (error_msg or "unknown error")[:2000], "review_id": review_id},
            )
    except Exception as e:  # noqa: BLE001 - 标记失败本身不能再抛错
        logger.error(f"_mark_review_failed failed: {e}")


@router.post("/upload", status_code=status.HTTP_202_ACCEPTED)
async def upload_resume(
    _: object = Depends(require_scope(Scope.RESUME_UPLOAD)),  # noqa: B008
    file: UploadFile = File(..., description="简历 PDF 文件"),
    current: CurrentUser = Depends(get_current_user),
) -> Any:
    """上传简历并触发后台评审，立即返回 review_id（202）。"""
    # 1. 校验类型
    if not (file.filename and file.filename.lower().endswith(tuple(ALLOWED_EXT))):
        raise HTTPException(status_code=400, detail="仅支持 PDF 文件")

    # 2. 读取并校验大小
    file_bytes = await file.read()
    if len(file_bytes) > config.qa.max_upload_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"文件超过 {config.qa.max_upload_mb}MB 上限")
    if len(file_bytes) == 0:
        raise HTTPException(status_code=400, detail="空文件")

    # 3. 租户/用户上下文（数据隔离 + 审计归属）。
    # 租户必填、超管无权限由 api/router.py 的组级 require_tenant() 保证，端点内不再重复校验。
    tenant_id = current.tenant_id
    user_id = current.user_id
    review_id = str(uuid6.uuid7())
    minio_key = build_object_key(filetype="resumes", tenant_id=tenant_id, user_id=user_id, name=review_id, ext="pdf")

    # 4. 上传到 MinIO
    try:
        storage = await get_storage()
        await asyncio.to_thread(storage.put_bytes, minio_key, file_bytes, content_type="application/pdf")
    except Exception as e:  # noqa: BLE001
        logger.error(f"upload_resume minio failed: {e}")
        raise HTTPException(status_code=502, detail="文件存储失败")

    # 5. 写骨架行（JSON 列留空，评审完成后回填；审计列按要求注入）
    try:
        async with session_scope() as session:
            await session.execute(
                text(
                    """
                    INSERT INTO agent_resume_reviews
                        (id, tenant_id, user_id, pdf_minio_path, status,
                         create_user_id, update_user_id, create_tenant_id, update_tenant_id)
                    VALUES
                        (:id, :tenant_id, :user_id, :pdf_minio_path, 'processing',
                         :create_user_id, :update_user_id, :create_tenant_id, :update_tenant_id)
                    """
                ),
                {
                    "id": review_id,
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                    "pdf_minio_path": minio_key,
                    "create_user_id": user_id,
                    "update_user_id": user_id,
                    "create_tenant_id": current.home_tenant_id,
                    "update_tenant_id": current.home_tenant_id,
                },
            )
    except Exception as e:  # noqa: BLE001
        logger.error(f"upload_resume db failed: {e}")
        raise HTTPException(status_code=500, detail="写入评审记录失败")

    # 6. 发消息队列，异步跑评审（消费者 handle_resume_review 经 Orchestrator 执行 LangGraph）。
    # 仅写 Outbox 即返回；broker 未启用时消息留存，启用后由 OutboxPublisher 补投。
    await enqueue_task(
        TaskType.RESUME_REVIEW,
        tenant_id=tenant_id,
        user_id=user_id,
        data={
            "review_id": review_id,
            "user_id": user_id,
            "tenant_id": tenant_id,
            "pdf_minio_path": minio_key,
        },
    )

    return success(
        {
            "review_id": review_id,
            "status": "processing",
            "message": "简历已接收，正在后台评审...",
        }
    )


@router.get("/reviews/{review_id}")
async def get_review(
    review_id: str,
    _: object = Depends(require_scope(Scope.RESUME_VIEW)),  # noqa: B008
    current: CurrentUser = Depends(get_current_user),
) -> Any:
    """查询单条评审结果（含超时兜底标记）。"""
    tenant_id = current.tenant_id
    user_id = current.user_id
    async with session_scope() as session:
        row = (
            await session.execute(
                text(
                    """
                    SELECT id, status, weighted_score, scores, issues, summary,
                           pdf_minio_path, error_msg, create_at, updated_at
                    FROM agent_resume_reviews
                    WHERE id = :id AND tenant_id = :tenant_id AND user_id = :user_id
                    """
                ),
                {"id": review_id, "tenant_id": tenant_id, "user_id": user_id},
            )
        ).mappings().first()

    if row is None:
        raise HTTPException(status_code=404, detail="评审记录不存在")

    # processing 超时兜底：长时间无响应则标记失败
    if row["status"] == "processing":
        created = row["create_at"]
        import datetime

        if created and (datetime.datetime.now() - created).total_seconds() > config.scheduler.resume_timeout_min * 60:
            await _mark_review_failed(review_id, "评审超时")
            row = {**dict(row), "status": "failed", "error_msg": "评审超时"}

    return success(
        {
            "review_id": str(row["id"]),
            "status": row["status"],
            "weighted_score": float(row["weighted_score"]) if row["weighted_score"] is not None else None,
            "dimension_scores": row["scores"],
            "issues": row["issues"],
            "summary": row["summary"],
            "pdf_minio_path": row["pdf_minio_path"],
            "error_msg": row["error_msg"],
            "created_at": row["create_at"].isoformat() if row["create_at"] else None,
            "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
        }
    )


@router.delete("/reviews/{review_id}")
async def delete_review(
    review_id: str,
    _: object = Depends(require_scope(Scope.RESUME_DELETE)),  # noqa: B008
    current: CurrentUser = Depends(get_current_user),
) -> Any:
    """删除一条评审记录（仅限本人同租户）。"""
    tenant_id = current.tenant_id
    user_id = current.user_id
    async with session_scope() as session:
        result = await session.execute(
            text(
                """
                DELETE FROM agent_resume_reviews
                WHERE id = :id AND tenant_id = :tenant_id AND user_id = :user_id
                """
            ),
            {"id": review_id, "tenant_id": tenant_id, "user_id": user_id},
        )
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="评审记录不存在")
    return success({"review_id": review_id, "deleted": True})


@router.get("/reviews", summary="评审记录列表（分页）")
async def list_reviews(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    _: object = Depends(require_scope(Scope.RESUME_PAGE)),  # noqa: B008
    current: CurrentUser = Depends(get_current_user),
) -> Any:
    params = {"tenant_id": current.tenant_id, "user_id": current.user_id}
    async with session_scope() as session:
        rows, total = await fetch_page(
            session, _LIST_REVIEWS, _COUNT_REVIEWS, params,
            page=page, page_size=page_size,
        )

    items = [
        {
            "review_id": str(r["id"]),
            "status": r["status"],
            "weighted_score": float(r["weighted_score"]) if r["weighted_score"] is not None else None,
            "pdf_minio_path": r["pdf_minio_path"],
            "created_at": r["create_at"].isoformat() if r["create_at"] else None,
            "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
        }
        for r in rows
    ]
    return success({"items": items, "total": total, "page": page, "page_size": page_size})
