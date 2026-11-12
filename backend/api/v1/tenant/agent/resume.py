"""简历审查接口：上传触发异步评审，结果按租户与用户隔离。"""

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
        logger.exception(f"_mark_review_failed failed: {e}")


@router.get("/reviews/{review_id}")
async def get_review(
    review_id: str,
    _: object = Depends(require_scope(Scope.RESUME_VIEW)),  # noqa: B008
    current: CurrentUser = Depends(get_current_user),
) -> Any:
    """查询单条评审结果，含超时兜底标记。

    说明：processing 超过阈值时标记 failed 再返回。
    请求：path { review_id }
    权限：resume:view
    返回：status / weighted_score / dimension_scores / issues / summary / ...
    """
    tenant_id = current.tenant_id
    user_id = current.user_id
    async with session_scope() as session:
        row = (
            (
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
            )
            .mappings()
            .first()
        )

    if row is None:
        raise HTTPException(status_code=404, detail="评审记录不存在")

    # processing 超时兜底：长时间无响应则标记失败
    if row["status"] == "processing":
        created = row["create_at"]
        import datetime

        if (
            created
            and (datetime.datetime.now() - created).total_seconds()
            > config.scheduler.resume_timeout_min * 60
        ):
            await _mark_review_failed(review_id, "评审超时")
            row = {**dict(row), "status": "failed", "error_msg": "评审超时"}

    return success(
        {
            "review_id": str(row["id"]),
            "status": row["status"],
            "weighted_score": float(row["weighted_score"])
            if row["weighted_score"] is not None
            else None,
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
    """删除一条评审记录（仅限本人同租户）。

    请求：path { review_id }
    权限：resume:delete
    返回：{ review_id, deleted }
    """
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
    """分页查询当前用户的评审记录。

    请求：query { page, page_size }
    权限：resume:page
    返回：items / total / page / page_size
    """
    params = {"tenant_id": current.tenant_id, "user_id": current.user_id}
    async with session_scope() as session:
        rows, total = await fetch_page(
            session,
            _LIST_REVIEWS,
            _COUNT_REVIEWS,
            params,
            page=page,
            page_size=page_size,
        )

    items = [
        {
            "review_id": str(r["id"]),
            "status": r["status"],
            "weighted_score": float(r["weighted_score"])
            if r["weighted_score"] is not None
            else None,
            "pdf_minio_path": r["pdf_minio_path"],
            "created_at": r["create_at"].isoformat() if r["create_at"] else None,
            "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
        }
        for r in rows
    ]
    return success({"items": items, "total": total, "page": page, "page_size": page_size})
