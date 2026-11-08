"""模拟面试直连接口（SSE 多轮）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.agents.interview.agent import InterviewAgent
from backend.middleware.auth import CurrentUser, get_current_user
from backend.security.rbac import Scope
from backend.security.security import require_scope

router = APIRouter(prefix="/interview", tags=["interview"])
_agent = InterviewAgent()


@router.post("/start", summary="发起模拟面试")
async def start(
    body: dict,
    _: object = Depends(require_scope(Scope.INTERVIEW_ASK)),  # noqa: B008
    current: CurrentUser = Depends(get_current_user),  # noqa: B008
) -> dict:
    return {"agent_type": _agent.agent_type, "received": body}
