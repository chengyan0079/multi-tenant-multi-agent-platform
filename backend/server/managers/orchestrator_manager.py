"""编排器：注册业务 Agent 图 + Orchestrator 单例。"""

from __future__ import annotations

from backend.agents import iter_agent_classes, load_agent_modules
from backend.app_state import app_state
from backend.orchestration.agent_registry import AgentRegistry
from backend.orchestration.orchestrator import Orchestrator
from backend.server.base_manager import BaseManager, HealthInfo


class OrchestratorManager(BaseManager):
    async def start(self) -> None:
        registry = AgentRegistry()
        # 加载所有业务 Agent 子模块（触发基于继承的自动登记），再收集已注册子类注册到编排器
        load_agent_modules()
        for agent_cls in iter_agent_classes():
            agent_cls().register_into(registry)
        # 从库加载持久化元数据与租户级开通策略（含 agent 表的启用状态，失败仅告警，不阻断）
        await registry.start()
        # 以 agent 表的启用状态为准，同步注册表开关；库未登记者保留代码默认值
        for agent_type in registry.list_types(only_enabled=False):
            meta = registry.get(agent_type)
            if meta.db_enabled is not None:
                registry.set_enabled(agent_type, meta.db_enabled)
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
        # 注册表对象存在但库规格加载失败：核心可用、能力降级，按 R15/Q6 报 degraded
        if not app_state.agent_registry.db_loaded:
            return HealthInfo(
                status="degraded",
                detail="agent_registry 库加载失败，仅代码注册 Agent 可用",
            )
        return HealthInfo(status="running")
