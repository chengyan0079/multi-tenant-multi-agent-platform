"""知识沉淀待审队列：教师复核（list / resolve / dismiss）。

挂在 /api/v1/tenant/knowledge/pending，整组 require_tenant()（按租户隔离）；
所有端点 require_scope(Scope.KNOWLEDGE_REVIEW)。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.common.response import success
from backend.security.rbac import Scope
from backend.security.security import CurrentUser, get_current_user, require_scope
from backend.data.dao.business.knowledge_pending_queue_dao import KnowledgePendingQueueDao

router = APIRouter(prefix="/knowledge/pending", tags=["knowledge-pending"])


def _serialize(rows: list[dict]) -> list[dict]:
    for r in rows:
        if r.get("create_at") is not None:
            r["create_at"] = r["create_at"].isoformat()
        if r.get("resolved_at") is not None:
            r["resolved_at"] = r["resolved_at"].isoformat()
    return rows


@router.get("", dependencies=[Depends(require_scope(Scope.KNOWLEDGE_REVIEW))])
async def list_pending(
    current: CurrentUser = Depends(get_current_user),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    """列出本租户待复核条目（pending）。"""
    items = await KnowledgePendingQueueDao.list_pending(
        tenant_id=current.tenant_id, limit=page_size, offset=(page - 1) * page_size
    )
    total = await KnowledgePendingQueueDao.count_pending(current.tenant_id)
    return success(data={"items": _serialize(items), "total": total, "page": page, "page_size": page_size})


@router.post("/{queue_id}/resolve", dependencies=[Depends(require_scope(Scope.KNOWLEDGE_REVIEW))])
async def resolve_pending(
    queue_id: str,
    current: CurrentUser = Depends(get_current_user),
):
    """复核通过：标记为 resolved（待补充知识库）。"""
    n = await KnowledgePendingQueueDao.resolve(
        queue_id=queue_id,
        tenant_id=current.tenant_id,
        resolved_user_id=current.user_id,
        status="resolved",
    )
    if n == 0:
        raise HTTPException(status_code=404, detail="待审条目不存在或已处理")
    return success(message="已标记为 resolved")


@router.post("/{queue_id}/dismiss", dependencies=[Depends(require_scope(Scope.KNOWLEDGE_REVIEW))])
async def dismiss_pending(
    queue_id: str,
    current: CurrentUser = Depends(get_current_user),
):
    """驳回：标记为 dismissed（不补充知识库）。"""
    n = await KnowledgePendingQueueDao.resolve(
        queue_id=queue_id,
        tenant_id=current.tenant_id,
        resolved_user_id=current.user_id,
        status="dismissed",
    )
    if n == 0:
        raise HTTPException(status_code=404, detail="待审条目不存在或已处理")
    return success(message="已标记为 dismissed")
