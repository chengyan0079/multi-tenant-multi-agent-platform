"""统一咨询入口：会话 CRUD / 回放 / 产物（§8.1，scope unified:ask）。

聊天框内历史列表、详情回放、删除、附件产物均走本组；管理端见 unified_session_admin。
所有查询强制 tenant_id + user_id（§5.3）。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from backend.api.v1.tenant.agent import unified_deps
from backend.api.v1.tenant.agent.unified_dtos import (
    ArtifactListView,
    CreateSessionRequest,
    DeleteSessionResponse,
    SessionListResponse,
    SessionPageQuery,
)
from backend.common.response import success
from backend.data.dao.agent.thread_dao import ThreadDao
from backend.data.dao.agent.unified_turn_dao import UnifiedTurnDao
from backend.middleware.auth import CurrentUser, get_current_user, tenant_of
from backend.security.rbac import Scope
from backend.security.security import require_scope

router = APIRouter(prefix="/unified", tags=["unified"])


@router.post("/sessions")
async def create_session(
    req: CreateSessionRequest,
    current: CurrentUser = Depends(get_current_user),
    _: object = Depends(require_scope(Scope.UNIFIED_ASK)),
) -> Any:
    tenant_id = tenant_of(current)
    session_key = req.session_id or unified_deps.new_session_key()
    tid = await ThreadDao.get_or_create(
        session_key=session_key, tenant_id=tenant_id, user_id=current.user_id
    )
    if req.title:
        await ThreadDao.update_title_if_default(
            thread_id=tid, tenant_id=tenant_id, user_id=current.user_id, title=req.title
        )
    row = await ThreadDao.get_session(
        tenant_id=tenant_id, user_id=current.user_id, thread_id=tid
    )
    turns = await UnifiedTurnDao.list_recent_by_thread(
        thread_id=tid, tenant_id=tenant_id, user_id=current.user_id
    )
    return success(unified_deps.to_session_detail(row, turns))


@router.get("/sessions")
async def list_sessions(
    q: SessionPageQuery = Depends(),
    current: CurrentUser = Depends(get_current_user),
    _: object = Depends(require_scope(Scope.UNIFIED_ASK)),
) -> Any:
    rows, total = await ThreadDao.list_sessions(
        tenant_id=tenant_of(current),
        user_id=current.user_id,
        page=q.page,
        page_size=q.page_size,
        status=q.status,
    )
    items = [unified_deps.to_session_item(r) for r in rows]
    return success(
        SessionListResponse(items=items, total=total, page=q.page, page_size=q.page_size)
    )


@router.get("/sessions/{thread_id}")
async def get_session(
    thread_id: str,
    current: CurrentUser = Depends(get_current_user),
    _: object = Depends(require_scope(Scope.UNIFIED_ASK)),
) -> Any:
    tenant_id = tenant_of(current)
    row = await ThreadDao.get_session(
        tenant_id=tenant_id, user_id=current.user_id, thread_id=thread_id
    )
    if not row:
        raise HTTPException(status_code=404, detail="会话不存在")
    turns = await UnifiedTurnDao.list_recent_by_thread(
        thread_id=thread_id, tenant_id=tenant_id, user_id=current.user_id
    )
    return success(unified_deps.to_session_detail(row, turns))


@router.delete("/sessions/{thread_id}")
async def delete_session(
    thread_id: str,
    current: CurrentUser = Depends(get_current_user),
    _: object = Depends(require_scope(Scope.UNIFIED_ASK)),
) -> Any:
    tenant_id = tenant_of(current)
    n = await ThreadDao.delete_session(
        tenant_id=tenant_id, user_id=current.user_id, thread_id=thread_id
    )
    if n == 0:
        raise HTTPException(status_code=404, detail="会话不存在")
    return success(DeleteSessionResponse(deleted=n))


@router.get("/sessions/{thread_id}/artifacts")
async def list_artifacts(
    thread_id: str,
    current: CurrentUser = Depends(get_current_user),
    _: object = Depends(require_scope(Scope.UNIFIED_ASK)),
) -> Any:
    arts = await UnifiedTurnDao.list_artifacts(
        thread_id=thread_id, tenant_id=tenant_of(current), user_id=current.user_id
    )
    return success(ArtifactListView(items=arts, total=len(arts)))
