"""会话状态 / HITL resume。

会话按「租户 + 用户」隔离：拿到别人的 thread_id 也只能得到 404，不暴露会话是否存在。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from backend.app_state import app_state
from backend.data.dao.agent.thread_dao import ThreadDao
from backend.middleware.auth import CurrentUser, get_current_user, tenant_of
from backend.observability.exception import BizException, ErrCode
from backend.api.v1.tenant.chat.schemas import ResumeIn
from backend.security.rbac import Scope
from backend.security.security import require_scope

router = APIRouter(prefix="/threads", tags=["threads"])


async def _assert_owned(thread_id: str, current: CurrentUser) -> None:
    """校验会话归属；不属于当前用户（或根本不存在）统一 404。"""
    owned = await ThreadDao.is_owned(
        thread_id=thread_id, tenant_id=tenant_of(current), user_id=current.user_id
    )
    if not owned:
        raise BizException(ErrCode.NOT_FOUND, "会话不存在")


@router.get("/{thread_id}")
async def get_thread(
    thread_id: str,
    _: object = Depends(require_scope(Scope.QA_PAGE)),  # noqa: B008
    current: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """取会话状态（从 checkpointer / 业务表）。"""
    await _assert_owned(thread_id, current)
    return {"thread_id": thread_id, "status": "ok"}


@router.post("/{thread_id}/resume")
async def resume_thread(
    thread_id: str,
    body: ResumeIn,
    _: object = Depends(require_scope(Scope.QA_ASK)),  # noqa: B008
    current: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """HITL 注入决策后继续被 interrupt 挂起的图。"""
    await _assert_owned(thread_id, current)
    orch = app_state.orchestrator
    if orch is None:
        raise BizException(ErrCode.INTERNAL, "orchestrator 未就绪")
    return await orch.resume(body.agent_type, thread_id, body.value)
