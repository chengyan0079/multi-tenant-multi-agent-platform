"""编排器：从 DB 加载注册 + Orchestrator 单例。"""

from __future__ import annotations

from backend.agents import AGENT_BUILDERS
from backend.app_state import app_state
from backend.orchestration.agent_registry import AgentRegistry
from backend.orchestration.orchestrator import Orchestrator
from backend.server.base_manager import BaseManager, HealthInfo


class OrchestratorManager(BaseManager):
    async def start(self) -> None:
        # 唯一注册源：DB（agent 表 tenant_id + enabled）；代码侧只提供 AGENT_BUILDERS
        registry = AgentRegistry(agent_builders=AGENT_BUILDERS)
        await registry.start()
        app_state.agent_registry = registry
        app_state.orchestrator = Orchestrator(registry)

    async def stop(self) -> None:
        if app_state.orchestrator is not None:
            await app_state.orchestrator.stop()
            app_state.orchestrator = None
        if app_state.agent_registry is not None:
            await app_state.agent_registry.stop()
            app_state.agent_registry = None

    async def health(self) -> HealthInfo:
        if app_state.orchestrator is None or app_state.agent_registry is None:
            return HealthInfo(status="down", detail="orchestrator/registry 未初始化")
        # 注册表对象存在但库规格加载失败：核心可用、能力降级
        if not app_state.agent_registry.db_loaded:
            return HealthInfo(
                status="degraded",
                detail="agent_registry 库加载失败，仅代码注册 Agent 可用",
            )
        return HealthInfo(status="running")
