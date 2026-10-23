"""插件管理：启动扫描 / 注册 / 隔离 / 启停。"""
from __future__ import annotations

from backend.app_state import app_state
from backend.plugins.loader import load_all
from backend.plugins.registry import PluginRegistry
from backend.server.base_manager import BaseManager


class PluginManager(BaseManager):
    async def start(self) -> None:
        registry = PluginRegistry()
        await load_all(registry)
        app_state.plugin_registry = registry

    async def stop(self) -> None:
        if app_state.plugin_registry is not None:
            await app_state.plugin_registry.stop()
            app_state.plugin_registry = None
