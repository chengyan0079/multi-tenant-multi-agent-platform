"""插件管理：以 DB 启用清单为白名单，装配运行时单例注册表。"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from backend.app_state import app_state
from backend.common.logger import get_logger
from backend.data.dao.agent.plugin_dao import PluginDao
from backend.mcp.loader import discover_builtin
from backend.mcp.registry import PluginRegistry
from backend.server.base_manager import BaseManager, HealthInfo

logger = get_logger("plugin_manager")

_reload_lock = asyncio.Lock()


def _parse_config(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    value = json.loads(raw)
    return value if isinstance(value, dict) else {}


async def _build_registry() -> PluginRegistry:
    rows = await PluginDao.list_enabled()
    enabled = {r["name"]: r for r in rows}
    registry = PluginRegistry()

    for plugin in discover_builtin():
        row = enabled.get(plugin.manifest.name)
        if row is None:
            continue
        try:
            plugin.configure(_parse_config(row["config"]))
        except (ValueError, TypeError) as exc:
            logger.exception(f"插件 config 非法，跳过: {plugin.manifest.name} - {exc}")
            continue
        registry.register_plugin(plugin)

    # 插件 register() 只在 start() 里执行，完成单例初始化
    await registry.start()
    return registry


async def reload_plugins() -> int:
    """重建注册表并原子替换；供启动、管理端点、跨副本消息共同调用。"""
    async with _reload_lock:
        previous = app_state.plugin_registry
        registry = await _build_registry()
        app_state.plugin_registry = registry
        if previous is not None:
            await previous.stop()
        if registry.plugin_count == 0:
            logger.warning("插件注册表为空：agent_plugin 无启用记录或与代码实现无匹配")
        return registry.plugin_count


class PluginManager(BaseManager):
    async def start(self) -> None:
        await reload_plugins()

    async def stop(self) -> None:
        if app_state.plugin_registry is not None:
            await app_state.plugin_registry.stop()
            app_state.plugin_registry = None

    async def health(self) -> HealthInfo:
        reg = app_state.plugin_registry
        if reg is None:
            return HealthInfo(status="down", detail="plugin_registry 未初始化")
        if reg.plugin_count == 0:
            return HealthInfo(status="degraded", detail="无启用插件")
        return HealthInfo(status="running", detail=f"plugins={reg.plugin_count}")
