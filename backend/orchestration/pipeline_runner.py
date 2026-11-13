"""多 Agent 串联执行器：逐步鉴权 → 分区 → run_agent → 归一为 PipelineCarry。"""
from __future__ import annotations

from typing import Any, Callable, Optional

from backend.orchestration.agent_spec import AgentSpec
from backend.orchestration.unified_dispatch import fork_config
from backend.orchestration.unified_schemas import (
    AgentOutcome,
    ArtifactRef,
    PipelineCarry,
    PipelinePlan,
    PipelineResultEvent,
    PipelineStepResultEvent,
    UnifiedEvent,
)
from backend.orchestration.unified_schemas import ErrorEvent


class PipelineRunner:
    """多 Agent 串联执行器：按 plan.steps 逐步执行并汇总事件。"""

    def __init__(
        self,
        *,
        orchestrator: Any,
        adapter: Any,
        registry: Any,
        authz: Optional[Callable[[str, int, int], bool]] = None,
    ) -> None:
        self._orchestrator = orchestrator
        self._adapter = adapter
        self._registry = registry
        self._authz = authz

    async def run(
        self,
        *,
        plan: PipelinePlan,
        cfg_U: dict,
        thread_id: str,
        tenant_id: int,
        user_id: int,
        trace_id: str,
        turn_id: str,
        conversation_service: Any = None,
    ) -> AgentOutcome:
        """按 plan.steps 逐步执行；返回汇总 AgentOutcome（含逐步事件）。"""
        events: list[UnifiedEvent] = []
        carry = PipelineCarry()

        for idx, step in enumerate(plan.steps):
            spec: Optional[AgentSpec] = self._spec_for(step.agent_type)
            if spec is None:
                return AgentOutcome(
                    content="",
                    events=[
                        UnifiedEvent(
                            event_type="error",
                            payload=ErrorEvent(
                                code="AGENT_DISABLED",
                                message=f"pipeline 步骤指向未知 Agent: {step.agent_type}",
                            ),
                        )
                    ],
                    state_patch=None,
                    persistence=None,
                )

            # 逐步鉴权
            if self._authz is not None and not self._authz(step.agent_type, tenant_id, user_id):
                return AgentOutcome(
                    content="",
                    events=[
                        UnifiedEvent(
                            event_type="error",
                            payload=ErrorEvent(
                                code="FORBIDDEN",
                                message=f"pipeline 步骤无权限或不开通: {step.agent_type}",
                            ),
                        )
                    ],
                    state_patch=None,
                    persistence=None,
                )

            partition = f"{thread_id}:{step.agent_type}:{turn_id}"
            cfg = fork_config(cfg_U, thread_id=partition)
            initial = self._adapter.to_subgraph_input(
                unified_state={"messages": [], "existing_summary": carry.content},
                spec=spec,
                entry=None,
                attachments=[],
            )
            result = await self._orchestrator.run_agent(step.agent_type, partition, initial)
            outcome = self._adapter.from_subgraph_output(result, spec)
            carry = PipelineCarry(content=outcome.content, artifacts=[])

            step_event = UnifiedEvent(
                event_type="pipeline_step_result",
                payload=PipelineStepResultEvent(
                    step=step.step,
                    agent_type=step.agent_type,
                    content=outcome.content,
                    artifacts=carry.artifacts,
                ),
            )
            events.append(step_event)

            if conversation_service is not None:
                await conversation_service.append_turn(
                    thread_id=thread_id,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    agent_type=step.agent_type,
                    spec_version=spec.version or "",
                    trace_id=trace_id,
                    turn_index=-(idx + 1),  # 负数区分 pipeline 子步（避免与主轮冲突）
                    event_type="pipeline_step",
                    user_content=None,
                    assistant_content=outcome.content,
                    payload={"step": step.step, "agent_type": step.agent_type},
                    routing={"execution_mode": "pipeline", "step": step.step},
                    status="success",
                )

        events.append(
            UnifiedEvent(
                event_type="pipeline_result",
                payload=PipelineResultEvent(
                    content=carry.content, artifacts=carry.artifacts, trace_id=trace_id
                ),
            )
        )
        return AgentOutcome(
            content=carry.content, events=events, state_patch=None, persistence=None
        )

    def _spec_for(self, agent_type: str) -> Optional[AgentSpec]:
        """按 agent_type 查注册表 spec；未注册返回 None。"""
        for s in self._registry.specs():
            if s.agent_type == agent_type:
                return s
        return None
