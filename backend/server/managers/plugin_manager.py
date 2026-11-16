"""插件管理：内置插件注册 + 按租户（agent_tool enabled）登记工具集合。

统一由 `agent_tool` 维护（工具类型/租户/启停/配置），不再使用 `agent_plugin`。
- 内置插件实例全局注册（代码能力）；
- 租户可用工具集合来自 `agent_tool`（tenant_id + enabled），逐租户输出日志；
- 工具运行配置由各工具按租户从 `agent_tool.config` 读取（不在此 configure）。
"""

from __future__ import annotations

import asyncio
from typing import Any

from backend.app_state import app_state
from backend.common.logger import get_logger
from backend.data.dao.agent.tool_dao import ToolDao
from backend.mcp.loader import discover_builtin
from backend.mcp.registry import PluginRegistry
from backend.server.base_manager import BaseManager, HealthInfo

logger = get_logger("plugin_manager")

_reload_lock = asyncio.Lock()


async def _build_registry() -> PluginRegistry:
    """**一切从 `agent_tool` 获取**：注册集合 = agent_tool 中已启用的工具（去重），
    代码只提供实现（discover_builtin 按 name 匹配），不注册表里没有的插件。
    """
    builtin = {p.manifest.name: p for p in discover_builtin()}
    enabled_rows = await ToolDao.list_all_enabled()  # [{tenant_id, name}]
    wanted = {str(r["name"]) for r in enabled_rows}

    registry = PluginRegistry()
    for name in sorted(wanted):
        plugin = builtin.get(name)
        if plugin is None:
            logger.warning(f"agent_tool 已注册工具但无代码实现，跳过: {name}")
            continue
        registry.register_plugin(plugin)
    # 插件 register() 只在 start() 里执行，完成单例初始化
    await registry.start()

    mapping: dict[int, set[str]] = {}
    for item in enabled_rows:
        tenant_id = int(item["tenant_id"])
        name = str(item["name"])
        mapping.setdefault(tenant_id, set()).add(name)
        logger.info(f"租户 {tenant_id} 注册工具 {name}")
    registry.set_tenant_tools(mapping)
    if not mapping:
        logger.warning("未发现任何租户启用的工具（agent_tool 无 enabled 记录）")
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
            logger.warning("插件注册表为空：agent_tool 无启用记录或与代码实现无匹配")
        return registry.plugin_count


class PluginManager(BaseManager):
    async def start(self) -> None:
        await reload_plugins()

    async def stop(self) -> None:
        if app_state.plugin_registry is not None:
            await app_state.plugin_registry.stop()
            app_state.plugin_registry = None

    async def startup_stats(self) -> str | None:
        reg = app_state.plugin_registry
        if reg is None:
            return None
        return f"插件={reg.plugin_count}"

    async def health(self) -> HealthInfo:
        reg = app_state.plugin_registry
        if reg is None:
            return HealthInfo(status="down", detail="plugin_registry 未初始化")
        if reg.plugin_count == 0:
            return HealthInfo(status="degraded", detail="无启用插件")
        return HealthInfo(status="running", detail=f"plugins={reg.plugin_count}")
