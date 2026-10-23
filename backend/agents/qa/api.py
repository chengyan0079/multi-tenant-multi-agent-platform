"""智能问答直连接口。"""
from __future__ import annotations

from fastapi import APIRouter

from backend.agents.qa.agent import QAAgent

router = APIRouter(prefix="/qa", tags=["qa"])
_agent = QAAgent()


@router.post("/ask")
async def ask(body: dict) -> dict:
    return {"agent_type": _agent.agent_type, "received": body}
