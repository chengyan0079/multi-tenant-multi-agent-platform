"""Web 搜索 MCP 客户端：经 streamable HTTP 调用本进程挂载的 MCP Server。"""
from __future__ import annotations

from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from backend.common.logger import get_logger
from backend.config import config
from backend.data.dao.agent.tool_dao import get_tool_config

logger = get_logger("mcp.client")
_TOOL_NAME = "web_search"


def default_mcp_url() -> str:
    """默认指向本进程挂载的 MCP Server；可被 agent_tool.config.url 覆盖。"""
    return f"http://127.0.0.1:{config.service.port}/mcp/web-search"


async def call_web_search(query: str, max_results: int, tenant_id: int) -> list[dict[str, Any]]:
    """调用联网搜索；配置每次现读 agent_tool，失败静默降级为空列表。"""
    if not query.strip():
        return []
    cfg = await get_tool_config(_TOOL_NAME, tenant_id)
    url = str(cfg.get("url") or default_mcp_url())
    limit = int(cfg.get("max_results") or max_results)

    try:
        async with streamable_http_client(url) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                result = await session.call_tool(
                    _TOOL_NAME, arguments={"query": query, "max_results": limit}
                )
        data = getattr(result, "structuredContent", None) or {}
        items = data.get("result", []) if isinstance(data, dict) else []
        return [i for i in items if isinstance(i, dict)] if isinstance(items, list) else []
    except Exception as exc:  # noqa: BLE001 - MCP 不可用降级为空，不阻断问答主链路
        logger.warning(f"web_search.mcp_failed | tenant={tenant_id} | {exc}")
        return []


async def is_mcp_available(tenant_id: int) -> bool:
    """MCP 可用性：agent_tool 该租户已启用 web_search。"""
    from backend.data.dao.agent.tool_dao import is_tool_enabled

    return await is_tool_enabled(tenant_id, _TOOL_NAME)
