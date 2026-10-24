"""编排与运维端点。"""
from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter

from backend.app_state import app_state

router = APIRouter(prefix="/orchestrator", tags=["orchestrator"])


@router.post("/run")
async def run(body: Dict[str, Any]) -> Dict[str, Any]:
    """指定 agent_type 或 pipeline_plan 运行。"""
    orch = app_state.orchestrator
    if orch is None:
        return {"error": "orchestrator 未就绪"}
    agent_type = body.get("agent_type")
    pipeline = body.get("pipeline_plan") or []
    thread_id = body.get("thread_id", "default")
    if pipeline:
        return await orch.run_pipeline(pipeline, thread_id, body.get("inputs", {}))
    return await orch.run_agent(agent_type, thread_id, body.get("inputs", {}))


@router.post("/resume")
async def resume(body: Dict[str, Any]) -> Dict[str, Any]:
    """HITL 注入决策后继续。"""
    orch = app_state.orchestrator
    if orch is None:
        return {"error": "orchestrator 未就绪"}
    return await orch.resume(body.get("agent_type", ""), body.get("thread_id", ""), body.get("value", {}))
