"""人工队列（控制台）。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from backend.app_state import app_state

router = APIRouter(prefix="/escalations", tags=["escalations"])


@router.get("")
async def list_escalations() -> dict[str, Any]:
    """人工队列列表（控制台查看 HITL 待确认项）。"""
    return {"items": [], "note": "列表查询接 AgentEscalation 模型（M3+）"}
