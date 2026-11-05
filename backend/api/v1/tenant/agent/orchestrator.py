"""编排与运维端点。"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.api.v1.tenant.agent.schemas import OrchestratorResumeIn, OrchestratorRunIn
from backend.app_state import app_state
from backend.middleware.auth import CurrentUser, get_current_user
from backend.observability.exception import BizException, ErrCode
from backend.security.rbac import Scope

router = APIRouter(prefix="/orchestrator", tags=["orchestrator"])

# agent_type -> 所需权限点（与 unified_chat 保持一致：问哪类就要求哪类的 ask 权限）
_SCOPE_BY_AGENT = {
    "qa": Scope.QA_ASK,
    "resume": Scope.RESUME_UPLOAD,
    "exam": Scope.EXAM_ASK,
    "interview": Scope.INTERVIEW_ASK,
}


def _assert_scope(current: CurrentUser, agent_type: str | None) -> None:
    """运行哪个 agent 就要求对应 ask 权限（"*" 视为全量）。"""
    required = _SCOPE_BY_AGENT.get(agent_type or "qa")
    if required is not None and required.value not in current.scopes and "*" not in current.scopes:
        raise BizException(ErrCode.FORBIDDEN, f"缺少权限 {required.value}")


@router.post("/run")
async def run(
    body: OrchestratorRunIn,
    current: CurrentUser = Depends(get_current_user),  # noqa: B008
) -> dict:
    """指定 agent_type 或 pipeline_plan 运行。"""
    orch = app_state.orchestrator
    if orch is None:
        raise BizException(ErrCode.INTERNAL, "orchestrator 未就绪")
    # 权限点：运行哪个 agent 就要求对应 ask 权限
    _assert_scope(current, body.agent_type)
    if body.pipeline_plan:
        return await orch.run_pipeline(body.pipeline_plan, body.thread_id, body.inputs)
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
