"""工具可用性守卫：调用前按租户判断工具是否启用，不可用返回原因而非抛异常。"""
from __future__ import annotations

from backend.app_state import app_state
from backend.common.logger import get_logger
from backend.data.dao.agent.tool_dao import is_tool_enabled

logger = get_logger("mcp.guard")
_MCP_TOOLS = frozenset({"web_search"})


async def check(tool_name: str, tenant_id: int) -> tuple[bool, str]:
    """返回 (可用, 原因)。web_search 走 DB 开关，其余工具走插件注册表。"""
    if tool_name in _MCP_TOOLS:
        if not await is_tool_enabled(tenant_id, tool_name):
            return False, f"租户未启用 MCP 工具: {tool_name}"
        return True, ""

    registry = app_state.plugin_registry
    if registry is None:
        return False, "插件注册表未就绪"
    if not registry.is_tool_enabled_for_tenant(tenant_id, tool_name):
        return False, f"租户未启用工具: {tool_name}"
    if registry.get_tool(tool_name) is None:
        return False, f"工具无实现: {tool_name}"
    return True, ""
