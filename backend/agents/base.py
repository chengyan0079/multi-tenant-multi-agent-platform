"""Agent 抽象基类：定义 State/节点/边/Checkpointer 装配套路，子类注册到 AgentRegistry。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from backend.orchestration.agent_registry import AgentRegistry


class Agent(ABC):
    """Agent 抽象基类。"""

    agent_type: str = ""

    @abstractmethod
    def build_graph(self) -> Any:
        """构造并编译 LangGraph（绑定 app_state.checkpointer）。"""
        raise NotImplementedError

    @abstractmethod
    def input_schema(self) -> Optional[dict]:
        """输入 JSON Schema，供校验与文档。"""
        raise NotImplementedError

    @abstractmethod
    def metadata(self) -> Dict[str, Any]:
        """Agent 元信息（描述、能力、流程形状等）。"""
        raise NotImplementedError

    def register_into(self, registry: AgentRegistry) -> None:
        """模块加载时调用，把本 Agent 注册进 AgentRegistry。"""
        registry.register(self.agent_type, self.build_graph, self.input_schema())
