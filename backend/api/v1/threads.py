"""会话状态 / HITL resume。"""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter

from backend.app_state import app_state

router = APIRouter(prefix="/v1/threads", tags=["threads"])


@router.get("/{thread_id}")
async def get_thread(thread_id: str) -> Dict[str, Any]:
    """取会话状态（从 checkpointer / 业务表）。"""
    return {"thread_id": thread_id, "status": "ok"}


@router.post("/{thread_id}/resume")
async def resume_thread(thread_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
    """HITL 注入决策后继续被 interrupt 挂起的图。"""
    orch = app_state.orchestrator
    if orch is None:
        return {"error": "orchestrator 未就绪"}
    agent_type = body.get("agent_type", "")
    return await orch.resume(agent_type, thread_id, body.get("value", {}))
