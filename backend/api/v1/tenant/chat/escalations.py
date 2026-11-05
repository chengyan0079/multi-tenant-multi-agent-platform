"""人工队列（控制台）。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from backend.app_state import app_state
from backend.middleware.auth import CurrentUser, get_current_user
from backend.security.rbac import Scope
from backend.security.security import require_scope

router = APIRouter(prefix="/escalations", tags=["escalations"])


@router.get("", summary="人工队列列表")
async def list_escalations(
    _: object = Depends(require_scope(Scope.QA_PAGE)),  # noqa: B008
    current: CurrentUser = Depends(get_current_user),  # noqa: B008
) -> dict[str, Any]:
    """人工队列列表（控制台查看 HITL 待确认项）。"""
    return {"items": [], "note": "列表查询接 AgentEscalation 模型（M3+）"}
