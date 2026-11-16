"""Agent 抽象基类：定义 State/节点/边/Checkpointer 装配套路，子类注册到 AgentRegistry。"""

from __future__ import annotations

import inspect
from abc import ABC, abstractmethod
from typing import Any, ClassVar

from backend.orchestration.agent_registry import AgentRegistry
from backend.orchestration.agent_spec import AgentSpec


class Agent(ABC):
    """Agent 抽象基类。

    继承本类的子类在定义时经 ``__init_subclass__`` 自动登记到 ``Agent._registry``，
    识别仅依赖继承关系（与文件路径、文件命名无关，不必叫 agent.py、不必放特定目录）。
    新增 Agent 只需在某处定义子类，无需在编排器或其它地方手动登记。
    """

    agent_type: str = ""

    # 自动登记的子类集合（仅具体、可实例化者）；识别与路径/命名解耦，只看继承关系。
    _registry: ClassVar[set] = set()  # 元素为 Agent 的具体子类

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        # 仅登记具体子类；抽象中间类由其具体子类触发登记（无需递归）
        if not inspect.isabstract(cls):
            Agent._registry.add(cls)

    @abstractmethod
    def build_graph(self) -> Any:
        """构造并编译 LangGraph（绑定 app_state.checkpointer）。"""
        raise NotImplementedError

    @abstractmethod
    def input_schema(self) -> dict | None:
        """输入 JSON Schema，供校验与文档。"""
        raise NotImplementedError

    @abstractmethod
    def metadata(self) -> AgentSpec:
        """Agent 元信息（统一入口规格，返回 AgentSpec）。"""
        raise NotImplementedError

    def register_into(self, registry: AgentRegistry) -> None:
        """模块加载时调用，把本 Agent 注册进 AgentRegistry。"""
        registry.register(
            self.agent_type,
            self.build_graph,
            self.input_schema(),
            spec=self.metadata(),
        )
