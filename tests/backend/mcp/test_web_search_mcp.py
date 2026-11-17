"""Web 搜索 MCP 链路测试：client 正常返回 / 异常降级，guard 租户开关。"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from backend.mcp.client import call_web_search
from backend.mcp.guard import check as tool_check


@pytest.mark.asyncio
async def test_call_web_search_returns_structured_content():
    """MCP 正常返回时取 structuredContent.result，转换为 list[dict]。"""
    result = SimpleNamespace(
        structuredContent={"result": [{"title": "t", "url": "u", "snippet": "s"}]}
    )
    session = AsyncMock()
    session.call_tool.return_value = result
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)

    with (
        patch("backend.mcp.client.streamable_http_client") as transport,
        patch("backend.mcp.client.ClientSession", return_value=session),
        patch("backend.mcp.client.get_tool_config", new=AsyncMock(return_value={})),
    ):
        transport.return_value.__aenter__ = AsyncMock(return_value=(object(), object()))
        transport.return_value.__aexit__ = AsyncMock(return_value=None)
        items = await call_web_search("query", 3, tenant_id=1)

    assert items == [{"title": "t", "url": "u", "snippet": "s"}]
    session.call_tool.assert_awaited_once()


@pytest.mark.asyncio
async def test_call_web_search_degrades_on_transport_error():
    """MCP 不可达时返回空列表，不抛异常。"""
    with (
        patch("backend.mcp.client.streamable_http_client", side_effect=OSError("down")),
        patch("backend.mcp.client.get_tool_config", new=AsyncMock(return_value={})),
    ):
        assert await call_web_search("query", 3, tenant_id=1) == []


@pytest.mark.asyncio
async def test_guard_blocks_mcp_tool_when_tenant_disabled():
    """web_search 走 DB 开关，租户未启用时拒绝。"""
    with patch(
        "backend.mcp.guard.is_tool_enabled", new=AsyncMock(return_value=False)
    ) as enabled:
        available, reason = await tool_check("web_search", tenant_id=9)

    assert available is False
    assert "未启用" in reason
    enabled.assert_awaited_once_with(9, "web_search")
