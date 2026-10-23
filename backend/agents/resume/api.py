"""简历审查直连接口。"""
from __future__ import annotations

from fastapi import APIRouter

from backend.agents.resume.agent import ResumeAgent

router = APIRouter(prefix="/resume", tags=["resume"])
_agent = ResumeAgent()


@router.post("/analyze")
async def analyze(body: dict) -> dict:
    """简历审查入口（骨架：经 Orchestrator 执行，此处仅暴露路由）。"""
    return {"agent_type": _agent.agent_type, "received": body}
