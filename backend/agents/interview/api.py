"""模拟面试直连接口（SSE 多轮）。"""
from __future__ import annotations

from fastapi import APIRouter

from backend.agents.interview.agent import InterviewAgent

router = APIRouter(prefix="/interview", tags=["interview"])
_agent = InterviewAgent()


@router.post("/start")
async def start(body: dict) -> dict:
    return {"agent_type": _agent.agent_type, "received": body}
