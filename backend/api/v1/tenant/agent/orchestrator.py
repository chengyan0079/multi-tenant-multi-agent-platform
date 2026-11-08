"""编排与运维端点。"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.api.v1.tenant.agent.schemas import OrchestratorResumeIn, OrchestratorRunIn
from backend.app_state import app_state
from backend.middleware.auth import CurrentUser, get_current_user
from backend.observability.exception import BizException, ErrCode
from backend.security.rbac import has_scope, scope_for_agent

router = APIRouter(prefix="/orchestrator", tags=["orchestrator"])


def _assert_scope(current: CurrentUser, agent_type: str | None) -> None:
    """运行哪个 agent 就要求对应权限（精确匹配；未登记类型一律拒绝）。"""
    required = scope_for_agent(agent_type or "qa")
    if required is None:
        raise BizException(ErrCode.FORBIDDEN, f"未登记的 agent 类型: {agent_type}")
    if not has_scope(current.scopes, required):
        raise BizException(ErrCode.FORBIDDEN, f"缺少权限 {required}")


@router.post("/run")
async def run(
    body: OrchestratorRunIn,
    current: CurrentUser = Depends(get_current_user),  # noqa: B008
) -> dict:
    """指定 agent_type 或 pipeline_plan 运行。"""
    orch = app_state.orchestrator
    if orch is None:
        raise BizException(ErrCode.INTERNAL, "orchestrator 未就绪")
    # 权限点：单 agent 校验该类型；pipeline 必须逐步校验，避免用单步权限绕过其它 agent
    if body.pipeline_plan:
        for step in body.pipeline_plan:
            _assert_scope(current, step)
        return await orch.run_pipeline(body.pipeline_plan, body.thread_id, body.inputs)
    if not body.agent_type:
        raise BizException(ErrCode.PARAM_ERROR, "agent_type 与 pipeline_plan 不能同时为空")
    _assert_scope(current, body.agent_type)
    return await orch.run_agent(body.agent_type, body.thread_id, body.inputs)


@router.post("/resume")
async def resume(
    body: OrchestratorResumeIn,
    current: CurrentUser = Depends(get_current_user),  # noqa: B008
) -> dict:
    """HITL 注入决策后继续。"""
    orch = app_state.orchestrator
    if orch is None:
        raise BizException(ErrCode.INTERNAL, "orchestrator 未就绪")
    _assert_scope(current, body.agent_type)
    return await orch.resume(body.agent_type, body.thread_id, body.value)
