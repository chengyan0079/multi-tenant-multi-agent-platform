"""试卷批改直连接口。"""
from __future__ import annotations

from fastapi import APIRouter

from backend.agents.exam.agent import ExamAgent

router = APIRouter(prefix="/exam", tags=["exam"])
_agent = ExamAgent()


@router.post("/grade")
async def grade(body: dict) -> dict:
    return {"agent_type": _agent.agent_type, "received": body}
