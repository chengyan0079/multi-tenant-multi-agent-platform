"""编排器：注册四 Agent 图 + Orchestrator 单例。"""
from __future__ import annotations

from backend.agents.exam.agent import ExamAgent
from backend.agents.interview.agent import InterviewAgent
from backend.agents.qa.agent import QAAgent
from backend.agents.resume.agent import ResumeAgent
from backend.app_state import app_state
from backend.core.agent_registry import AgentRegistry
from backend.core.orchestrator import Orchestrator
from backend.server.base_manager import BaseManager


class OrchestratorManager(BaseManager):
    async def start(self) -> None:
        registry = AgentRegistry()
        # 模块加载时注册四 Agent 图（新增 Agent 只加一行）
        for agent_cls in (ResumeAgent, QAAgent, ExamAgent, InterviewAgent):
            agent_cls().register_into(registry)
        app_state.agent_registry = registry
        app_state.orchestrator = Orchestrator(registry)

    async def stop(self) -> None:
        if app_state.orchestrator is not None:
            await app_state.orchestrator.stop()
            app_state.orchestrator = None
        if app_state.agent_registry is not None:
            await app_state.agent_registry.stop()
            app_state.agent_registry = None
