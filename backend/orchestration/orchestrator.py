"""
orchestrator - 编排器（设计文档 §3.2 / §3.3）

系统「前台 + 调度员」：不亲自干活，但知道每件事找谁。
- 单 Agent 直达：按 agent_type 从 AgentRegistry 取图执行。
- 多 Agent 串联 Pipeline：按 pipeline_plan 顺序串多个 Agent，前输出作后输入。
HITL 暂停恢复由图的 interrupt()/resume() 机制承载，这里只负责调度与状态透传。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from backend.app_state import app_state
from backend.common.logger import get_logger
from backend.orchestration.agent_registry import AgentRegistry
from backend.observability.exception import TenantError

logger = get_logger("orchestrator")


class Orchestrator:
    """编排内核：单 Agent 直达 + 多 Agent 串联。"""

    def __init__(self, registry: AgentRegistry) -> None:
        self._registry = registry

    async def start(self) -> None:
        return None

    async def run_agent(self, agent_type: str, thread_id: str,
                        inputs: Dict[str, Any]) -> Dict[str, Any]:
        """单 Agent 直达：取图 + checkpointer 执行，返回最终 state。"""
        meta = self._registry.get(agent_type)
        if not meta.enabled:
            raise TenantError(f"Agent 未开通: {agent_type}")
        graph = meta.build_graph()
        # checkpointer 由 CheckpointerManager 注入，支持多轮与 HITL 恢复
        cfg = {"configurable": {"thread_id": thread_id}}
        result = await graph.ainvoke(inputs, config=cfg)
        return dict(result)

    async def run_pipeline(self, pipeline_plan: List[str], thread_id: str,
                           inputs: Dict[str, Any]) -> Dict[str, Any]:
        """多 Agent 串联：依次执行，前一步 state 透传为下一步输入。"""
        carry: Dict[str, Any] = dict(inputs)
        for agent_type in pipeline_plan:
            logger.info(f"pipeline 步骤: {agent_type}")
            carry = await self.run_agent(agent_type, f"{thread_id}:{agent_type}", carry)
        return carry

    async def resume(self, agent_type: str, thread_id: str, value: Dict[str, Any]) -> Dict[str, Any]:
        """HITL 恢复：向被 interrupt() 挂起的图注入决策后继续。"""
        meta = self._registry.get(agent_type)
        graph = meta.build_graph()
        cfg = {"configurable": {"thread_id": thread_id}}
        result = await graph.ainvoke(value, config=cfg)
        return dict(result)

    async def stop(self) -> None:
        return None
