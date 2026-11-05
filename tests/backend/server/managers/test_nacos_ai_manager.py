"""NacosAIManager / build_mcp_release_params 单元测试（mock SDK，不连真 Nacos）。"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.app_state import app_state
from backend.config import config as app_config
from backend.server.managers.nacos_ai_manager import NacosAIManager
from backend.server.managers.nacos_ai_spec import build_mcp_release_params
from v2.nacos.ai.model.mcp.mcp import (
    McpEndpointSpec,
    McpServerBasicInfo,
    McpToolSpecification,
)


class _FakeNacosAI:
    enabled = True
    publish_mcp = True
    mcp_server_name = "agent-platform-mcp"
    mcp_protocol = "mcp-streamable"
    mcp_front_protocol = "mcp-streamable"
    mcp_description = "test mcp"
    mcp_version = "1.0.0"
    mcp_endpoint_path = "/mcp"
    mcp_capabilities = ["TOOL"]
    mcp_tools: list[dict] = []
    strict = False


class _FakeService:
    ip = "10.0.0.1"
    port = 9000


@pytest.fixture
def fake_cfg(monkeypatch: Any) -> None:
    monkeypatch.setattr(app_config, "nacos_ai", _FakeNacosAI())
    monkeypatch.setattr(app_config, "service", _FakeService())
    monkeypatch.setattr(app_state, "nacos_ai", None)


def test_build_mcp_release_params(fake_cfg: None) -> None:
    params = build_mcp_release_params(app_config.nacos_ai, app_config.service)

    assert isinstance(params["server_spec"], McpServerBasicInfo)
    assert params["server_spec"].name == "agent-platform-mcp"
    assert params["server_spec"].status == "active"
    assert params["server_spec"].capabilities[0].value == "TOOL"
    assert params["tool_spec"] is None
    assert isinstance(params["mcp_endpoint_spec"], McpEndpointSpec)
    assert params["mcp_endpoint_spec"].type == "DIRECT"
    assert params["mcp_endpoint_spec"].data["address"] == "10.0.0.1"
    assert params["mcp_endpoint_spec"].data["port"] == "9000"


def test_build_mcp_release_params_with_tools(fake_cfg: None) -> None:
    app_config.nacos_ai.mcp_tools = [
        {"name": "search", "description": "d", "inputSchema": {"type": "object"}}
    ]
    params = build_mcp_release_params(app_config.nacos_ai, app_config.service)
    assert isinstance(params["tool_spec"], McpToolSpecification)
    assert params["tool_spec"].tools[0].name == "search"


@pytest.fixture
def fake_client(monkeypatch: Any) -> MagicMock:
    client = MagicMock()
    client.is_connected = True
    client.raw = MagicMock()
    client.connect = AsyncMock()
    client.close = AsyncMock()
    client.release_mcp_server = AsyncMock(return_value="mcp-id-123")
    monkeypatch.setattr(app_state.clients, "ensure", lambda key, factory: client)
    return client


async def test_start_releases_mcp(fake_cfg: None, fake_client: MagicMock) -> None:
    mgr = NacosAIManager()
    await mgr.start()
    assert app_state.nacos_ai is mgr
    fake_client.release_mcp_server.assert_awaited_once()
    kwargs = fake_client.release_mcp_server.call_args.kwargs
    assert kwargs["server_spec"].name == "agent-platform-mcp"
    assert mgr._released_id == "mcp-id-123"

    info = await mgr.health()
    assert info.status == "running"

    await mgr.stop()
    fake_client.close.assert_awaited_once()
    assert app_state.nacos_ai is None


async def test_start_skips_when_disabled(
    monkeypatch: Any, fake_client: MagicMock
) -> None:
    cfg = _FakeNacosAI()
    cfg.enabled = False
    monkeypatch.setattr(app_config, "nacos_ai", cfg)
    mgr = NacosAIManager()
    await mgr.start()
    fake_client.connect.assert_not_called()
    assert app_state.nacos_ai is None


async def test_start_skips_when_not_publish(
    fake_cfg: None, fake_client: MagicMock
) -> None:
    app_config.nacos_ai.publish_mcp = False
    mgr = NacosAIManager()
    await mgr.start()
    fake_client.release_mcp_server.assert_not_awaited()
    info = await mgr.health()
    assert info.status == "degraded"  # 已连接但未发布
