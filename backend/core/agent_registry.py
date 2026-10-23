"""
agent_registry - Agent 与能力的注册/发现（设计文档 §3.2 / §15.1）

各 Agent 模块启动时 register(agent_type, build_graph, schema)；运行时按 agent_type 取图。
支持租户级 enable/disable（能力开关），与 PluginRegistry 联动。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from backend.common.logger import get_logger

logger = get_logger("agent_registry")


@dataclass
class AgentMeta:
    """一个 Agent 的注册元数据。"""

    agent_type: str
    build_graph: Callable[..., object]  # 返回编译后的 LangGraph (CompiledGraph)
    input_schema: Optional[dict] = None  # JSON Schema，供校验与文档
    enabled: bool = True


class AgentRegistry:
    """运行时 Agent 注册表：按 agent_type 找图，支持能力开关与按租户过滤。"""

    def __init__(self) -> None:
        self._agents: Dict[str, AgentMeta] = {}

    async def start(self) -> None:
        return None

    def register(self, agent_type: str, build_graph: Callable[..., object],
                 input_schema: Optional[dict] = None) -> None:
        """注册一个 Agent 图构造器；重复注册覆盖并告警。"""
        if agent_type in self._agents:
            logger.warning(f"Agent 重复注册，覆盖: {agent_type}")
        self._agents[agent_type] = AgentMeta(agent_type, build_graph, input_schema)
        logger.info(f"Agent 已注册: {agent_type}")

    def get(self, agent_type: str) -> AgentMeta:
        if agent_type not in self._agents:
            raise KeyError(f"未知 Agent 类型: {agent_type}")
        return self._agents[agent_type]

    def set_enabled(self, agent_type: str, enabled: bool) -> None:
        """租户级能力开关（全局维度；租户维度由 capability_policy 表控制，见 security）。"""
        meta = self.get(agent_type)
        meta.enabled = enabled

    def list_types(self, only_enabled: bool = True) -> List[str]:
        """列出已注册 Agent 类型。"""
        return [t for t, m in self._agents.items() if (m.enabled or not only_enabled)]

    async def stop(self) -> None:
        self._agents.clear()
