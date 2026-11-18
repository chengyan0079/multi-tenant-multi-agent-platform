"""冒烟测试：验证骨架模块可导入、核心抽象可实例化（不依赖外部存储）。"""
from __future__ import annotations

from backend.orchestration.agent_registry import AgentRegistry
from backend.orchestration.orchestrator import Orchestrator
from backend.tools.registry import PluginRegistry


def test_registries_instantiate() -> None:
    reg = AgentRegistry()
    orch = Orchestrator(reg)
    plugins = PluginRegistry()
    assert orch is not None and reg is not None and plugins is not None
