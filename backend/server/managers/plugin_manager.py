"""插件管理：启动扫描 / 注册 / 隔离 / 启停。"""
from __future__ import annotations

from backend.app_state import app_state
from backend.common.logger import get_logger
from backend.mcp.loader import load_all
from backend.mcp.registry import PluginRegistry
from backend.server.base_manager import BaseManager, HealthInfo

logger = get_logger("plugin_manager")


class PluginManager(BaseManager):
    async def start(self) -> None:
        registry = PluginRegistry()
        await load_all(registry)
        app_state.plugin_registry = registry
        # 就绪自检：至少加载到一个插件；空则告警（不阻断启动，registry 按非空判定）
        if registry.plugin_count == 0:
            logger.error(
                "插件就绪自检未通过：未加载任何插件（plugin_registry 为空），"
                "请检查 backend/plugins/builtin 下插件与 manifest"
            )

    async def stop(self) -> None:
        if app_state.plugin_registry is not None:
            await app_state.plugin_registry.stop()
            app_state.plugin_registry = None

    async def health(self) -> HealthInfo:
        reg = app_state.plugin_registry
        if reg is None:
            return HealthInfo(status="down", detail="plugin_registry 未初始化")
        if reg.plugin_count == 0:
            return HealthInfo(status="degraded", detail="未加载任何插件")
        return HealthInfo(status="running", detail=f"plugins={reg.plugin_count}")
