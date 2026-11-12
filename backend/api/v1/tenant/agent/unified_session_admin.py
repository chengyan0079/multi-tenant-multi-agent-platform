"""统一咨询入口：会话管理端（§8.1，scope unified_session:*）。

面向管理页：跨用户查看/删除本租户全部会话。查看前先做 role 校验
（require_scope 已拦截无权限调用方）；数据仍按 tenant_id 隔离。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.api.v1.tenant.agent import unified_deps
from backend.api.v1.tenant.agent.unified_dtos import (
    DeleteSessionResponse,
    SessionListResponse,
)
from backend.common.response import success
from backend.data.dao.agent.thread_dao import ThreadDao
from backend.data.dao.agent.unified_turn_dao import UnifiedTurnDao
from backend.middleware.auth import CurrentUser, get_current_user, tenant_of
from backend.security.rbac import Scope
from backend.security.security import require_scope

router = APIRouter(prefix="/unified/session-admin", tags=["unified-admin"])


@router.get("/sessions")
async def admin_list_sessions(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str | None = Query(None),
    current: CurrentUser = Depends(get_current_user),
    _: object = Depends(require_scope(Scope.UNIFIED_SESSION_PAGE)),
) -> Any:
    rows, total = await ThreadDao.list_sessions_admin(
        tenant_id=tenant_of(current), page=page, page_size=page_size, status=status
    )
    items = [unified_deps.to_session_item(r) for r in rows]
    return success(
        SessionListResponse(items=items, total=total, page=page, page_size=page_size)
    )


@router.get("/sessions/{thread_id}")
async def admin_get_session(
    thread_id: str,
    current: CurrentUser = Depends(get_current_user),
    _: object = Depends(require_scope(Scope.UNIFIED_SESSION_VIEW)),
) -> Any:
    tenant_id = tenant_of(current)
    row = await ThreadDao.get_session_admin(tenant_id=tenant_id, thread_id=thread_id)
    if not row:
        raise HTTPException(status_code=404, detail="会话不存在")
    turns = await UnifiedTurnDao.list_recent_by_thread(
        thread_id=thread_id, tenant_id=tenant_id, user_id=None
    )
    return success(unified_deps.to_session_detail(row, turns))


@router.delete("/sessions/{thread_id}")
async def admin_delete_session(
    thread_id: str,
    current: CurrentUser = Depends(get_current_user),
    _: object = Depends(require_scope(Scope.UNIFIED_SESSION_DELETE)),
) -> Any:
    tenant_id = tenant_of(current)
    n = await ThreadDao.delete_session_admin(tenant_id=tenant_id, thread_id=thread_id)
    if n == 0:
        raise HTTPException(status_code=404, detail="会话不存在")
    return success(DeleteSessionResponse(deleted=n))
