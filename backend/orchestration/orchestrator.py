"""编排器：单 Agent 直达 + 多 Agent 串联调度，HITL 由图的 interrupt/resume 承载。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from backend.app_state import app_state
from backend.common.logger import get_logger
from backend.orchestration.agent_registry import AgentRegistry
from backend.observability.exception import TenantError
from backend.observability.tracing import tracing

logger = get_logger("orchestrator")


class Orchestrator:
    """编排内核：单 Agent 直达 + 多 Agent 串联。"""

    def __init__(self, registry: AgentRegistry) -> None:
        self._registry = registry

    async def start(self) -> None:
        return None

    async def run_agent(
        self, agent_type: str, thread_id: str, inputs: Dict[str, Any]
    ) -> Dict[str, Any]:
        """单 Agent 直达：取图 + checkpointer 执行，返回最终 state。"""
        meta = self._registry.get(agent_type)
        if not meta.enabled:
            raise TenantError(f"Agent 未开通: {agent_type}")
        graph = meta.build_graph()
        # checkpointer 由 CheckpointerManager 注入，支持多轮与 HITL 恢复
        cfg = tracing.with_callbacks({"configurable": {"thread_id": thread_id}})
        result = await graph.ainvoke(inputs, config=cfg)
        return dict(result)

    async def run_pipeline(
        self, pipeline_plan: List[str], thread_id: str, inputs: Dict[str, Any]
    ) -> Dict[str, Any]:
        """多 Agent 串联：依次执行，前一步 state 透传为下一步输入。"""
        carry: Dict[str, Any] = dict(inputs)
        for agent_type in pipeline_plan:
            logger.info(f"pipeline 步骤: {agent_type}")
            carry = await self.run_agent(agent_type, f"{thread_id}:{agent_type}", carry)
        return carry

    async def resume(
        self, agent_type: str, thread_id: str, value: Dict[str, Any]
    ) -> Dict[str, Any]:
        """HITL 恢复：向被 interrupt() 挂起的图注入决策后继续。"""
        meta = self._registry.get(agent_type)
        graph = meta.build_graph()
        cfg = tracing.with_callbacks({"configurable": {"thread_id": thread_id}})
        result = await graph.ainvoke(value, config=cfg)
        return dict(result)

    async def stop(self) -> None:
        return None
