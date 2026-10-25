"""编排与运维端点。"""
from __future__ import annotations

from fastapi import APIRouter

from backend.api.v1.tenant.agent.schemas import OrchestratorResumeIn, OrchestratorRunIn
from backend.app_state import app_state
from backend.observability.exception import BizException, ErrCode

router = APIRouter(prefix="/orchestrator", tags=["orchestrator"])


@router.post("/run")
async def run(body: OrchestratorRunIn) -> dict:
    """指定 agent_type 或 pipeline_plan 运行。"""
    orch = app_state.orchestrator
    if orch is None:
        raise BizException(ErrCode.INTERNAL, "orchestrator 未就绪")
    if body.pipeline_plan:
        return await orch.run_pipeline(body.pipeline_plan, body.thread_id, body.inputs)
    return await orch.run_agent(body.agent_type, body.thread_id, body.inputs)


@router.post("/resume")
async def resume(body: OrchestratorResumeIn) -> dict:
    """HITL 注入决策后继续。"""
    orch = app_state.orchestrator
    if orch is None:
        raise BizException(ErrCode.INTERNAL, "orchestrator 未就绪")
    return await orch.resume(body.agent_type, body.thread_id, body.value)
