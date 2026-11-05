"""NacosAIClient 单元测试（mock SDK，不连真 Nacos）。

覆盖：MCP / Agent / Prompt / Skill 各方法构造正确 Param 并转发到 SDK、回传结果；
_guard_param 在 SDK 缺失时抛 ClientError；健康态反映连接态；connect 软降级与鉴权透传。
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from backend.data.clients.base import ClientError
from backend.data.clients.nacos import NacosAIClient
from backend.data.clients.nacos import ai as ai_module
from v2.nacos.ai.model.ai_param import (
    DownloadSkillParam,
    GetAgentCardParam,
    GetMcpServerParam,
    GetPromptParam,
    RegisterAgentEndpointParam,
    RegisterMcpServerEndpointParam,
    SubscribeMcpServerParam,
    SubscribePromptParam,
)


@pytest.fixture
def client() -> NacosAIClient:
    return NacosAIClient(
        server_addr="http://localhost:8848", namespace="3d523e88-a17f-4a90-88c5-d31793405818"
    )


# ---------------- MCP Server ----------------


async def test_get_mcp_server_forwards_param(client) -> None:
    client._raw = AsyncMock()
    client._raw.get_mcp_server = AsyncMock(return_value={"name": "mcp"})
    out = await client.get_mcp_server("mcp", version="1.0")
    assert out == {"name": "mcp"}
    arg = client._raw.get_mcp_server.call_args.args[0]
    assert isinstance(arg, GetMcpServerParam)
    assert arg.mcp_name == "mcp"
    assert arg.version == "1.0"


async def test_release_mcp_server_forwards(client) -> None:
    client._raw = AsyncMock()
    client._raw.release_mcp_server = AsyncMock(return_value=True)
    # server_spec/tool_spec 在 SDK 里是强类型模型，用替身绕过其校验，仅验证转发
    with patch.object(ai_module, "ReleaseMcpServerParam", _DummyParam):
        ok = await client.release_mcp_server({"server": 1}, {"tool": 2})
    assert ok is True
    arg = client._raw.release_mcp_server.call_args.args[0]
    assert isinstance(arg, _DummyParam)
    assert arg.server_spec == {"server": 1}
    assert arg.tool_spec == {"tool": 2}


async def test_register_mcp_server_endpoint_forwards(client) -> None:
    client._raw = AsyncMock()
    client._raw.register_mcp_server_endpoint = AsyncMock(return_value=True)
    ok = await client.register_mcp_server_endpoint("mcp", "1.2.3.4", 8080, version="1.0")
    assert ok is True
    arg = client._raw.register_mcp_server_endpoint.call_args.args[0]
    assert isinstance(arg, RegisterMcpServerEndpointParam)
    assert arg.mcp_name == "mcp" and arg.address == "1.2.3.4" and arg.port == 8080


async def test_subscribe_mcp_server_forwards(client) -> None:
    client._raw = AsyncMock()
    client._raw.subscribe_mcp_server = AsyncMock(return_value=None)
    cb = lambda x: None  # noqa: E731 - 仅用于身份断言
    await client.subscribe_mcp_server("mcp", "1.0", cb)
    arg = client._raw.subscribe_mcp_server.call_args.args[0]
    assert isinstance(arg, SubscribeMcpServerParam)
    assert arg.mcp_name == "mcp" and arg.subscribe_callback is cb


# ---------------- Agent Card ----------------


async def test_get_agent_card_forwards(client) -> None:
    client._raw = AsyncMock()
    client._raw.get_agent_card = AsyncMock(return_value={"name": "a"})
    out = await client.get_agent_card("agent", version="2")
    assert out == {"name": "a"}
    arg = client._raw.get_agent_card.call_args.args[0]
    assert isinstance(arg, GetAgentCardParam)
    assert arg.agent_name == "agent"


async def test_release_agent_card_forwards(client) -> None:
    client._raw = AsyncMock()
    client._raw.release_agent_card = AsyncMock(return_value=True)
    # agent_card 在 SDK 里是强类型模型，用替身绕过其校验，仅验证转发
    with patch.object(ai_module, "ReleaseAgentCardParam", _DummyParam):
        ok = await client.release_agent_card({"card": 1}, registration_type="service", set_as_latest=True)
    assert ok is True
    arg = client._raw.release_agent_card.call_args.args[0]
    assert isinstance(arg, _DummyParam)
    assert arg.set_as_latest is True
    assert arg.agent_card == {"card": 1}


async def test_register_and_deregister_agent_endpoint_forward(client) -> None:
    client._raw = AsyncMock()
    for m in ("register_agent_endpoint", "deregister_agent_endpoint"):
        setattr(client._raw, m, AsyncMock(return_value=True))
    assert await client.register_agent_endpoint("a", "1.1.1.1", 80, "1") is True
    assert await client.deregister_agent_endpoint("a", "1.1.1.1", 80, "1") is True
    reg = client._raw.register_agent_endpoint.call_args.args[0]
    assert isinstance(reg, RegisterAgentEndpointParam)
    assert reg.agent_name == "a" and reg.port == 80


# ---------------- Prompt / Skill ----------------


async def test_get_prompt_forwards(client) -> None:
    client._raw = AsyncMock()
    client._raw.get_prompt = AsyncMock(return_value={"key": "p"})
    out = await client.get_prompt("p", version="1", label="latest")
    assert out == {"key": "p"}
    arg = client._raw.get_prompt.call_args.args[0]
    assert isinstance(arg, GetPromptParam)
    assert arg.prompt_key == "p"


async def test_subscribe_prompt_and_unsubscribe_forward(client) -> None:
    client._raw = AsyncMock()
    for m in ("subscribe_prompt", "unsubscribe_prompt"):
        setattr(client._raw, m, AsyncMock(return_value=None))
    cb = lambda x: None  # noqa: E731
    await client.subscribe_prompt("p", "1", cb, label="latest")
    await client.unsubscribe_prompt("p", "1", cb, label="latest")
    assert isinstance(client._raw.subscribe_prompt.call_args.args[0], SubscribePromptParam)


async def test_download_skill_zip_forwards(client) -> None:
    client._raw = AsyncMock()
    client._raw.download_skill_zip = AsyncMock(return_value=b"zip")
    out = await client.download_skill_zip("skill", version="1", label="latest")
    assert out == b"zip"
    arg = client._raw.download_skill_zip.call_args.args[0]
    assert isinstance(arg, DownloadSkillParam)
    assert arg.skill_name == "skill"


# ---------------- 守卫 / 生命周期 ----------------


async def test_guard_param_raises_when_sdk_missing(client) -> None:
    # 模拟 SDK 缺失：把 Param 类置 None，_guard_param 应抛 ClientError
    with patch.object(ai_module, "GetMcpServerParam", None):
        with pytest.raises(ClientError):
            await client.get_mcp_server("mcp")


async def test_health_check_reflects_connection_state() -> None:
    c = NacosAIClient(server_addr="x", namespace="3d523e88-a17f-4a90-88c5-d31793405818")
    c._raw = AsyncMock()
    assert await c.health_check() is True
    c._raw = None
    assert await c.health_check() is False


async def test_connect_soft_degrades_when_sdk_absent() -> None:
    c = NacosAIClient(server_addr="x", namespace="3d523e88-a17f-4a90-88c5-d31793405818")
    with patch.object(ai_module, "NacosAIService", None):
        await c.connect()
    assert c.is_connected is False


_AI_CREATE_CAPTURE: dict = {}


class _DummyParam:
    """轻量 Param 替身：仅记录构造入参，用于验证客户端转发，避开 SDK 重型模型校验。"""

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class _FakeAIService:
    """替身 NacosAIService：捕获建连时传入的 ClientConfig。"""

    @classmethod
    async def create_ai_service(cls, cc):
        _AI_CREATE_CAPTURE["cc"] = cc
        return AsyncMock()


async def test_connect_builds_client_config_and_assigns() -> None:
    _AI_CREATE_CAPTURE.clear()
    c = NacosAIClient(
        server_addr="http://localhost:8848",
        namespace="3d523e88-a17f-4a90-88c5-d31793405818",
        user="nacos",
        password="pw",
    )
    with patch.object(ai_module, "NacosAIService", _FakeAIService):
        await c.connect()
    assert c.is_connected
    assert _AI_CREATE_CAPTURE["cc"].username == "nacos"
    assert _AI_CREATE_CAPTURE["cc"].password == "pw"
    assert _AI_CREATE_CAPTURE["cc"].namespace_id == "3d523e88-a17f-4a90-88c5-d31793405818"
