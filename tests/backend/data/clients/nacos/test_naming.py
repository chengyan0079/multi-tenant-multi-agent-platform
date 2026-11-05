"""NacosNamingClient 单元测试（mock SDK，不连真 Nacos）。

覆盖：命名空间归一化、未连接守卫、connect 建连与鉴权透传、各能力方法转发到 SDK。
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from backend.data.clients.base import ClientError
from backend.data.clients.nacos import NacosNamingClient


@pytest.fixture
def client() -> NacosNamingClient:
    return NacosNamingClient(server_addr="http://localhost:8848", namespace="public")


def test_namespace_public_normalizes_to_empty(client) -> None:
    # public -> 空串，避免公共命名空间被误当 UUID
    assert client._namespace == ""


def test_namespace_uuid_passthrough() -> None:
    c = NacosNamingClient(server_addr="x", namespace="3d523e88-a17f-4a90-88c5-d31793405818")
    assert c._namespace == "3d523e88-a17f-4a90-88c5-d31793405818"


def test_raw_raises_when_disconnected(client) -> None:
    with pytest.raises(ClientError):
        _ = client.raw


async def test_connect_builds_client_config_and_assigns(client) -> None:
    fake_raw = AsyncMock()
    captured: dict = {}

    async def fake_create(cc):
        captured["cc"] = cc
        return fake_raw

    with patch("v2.nacos.NacosNamingService.create_naming_service", new=fake_create):
        await client.connect()
    assert client.is_connected
    # 公共命名空间 namespace_id 应为空串；未设鉴权应为 None
    assert captured["cc"].namespace_id == ""
    assert captured["cc"].username is None
    assert client._raw is fake_raw


async def test_register_instance_forwards_to_raw(client) -> None:
    client._raw = AsyncMock()
    client._raw.register_instance = AsyncMock(return_value=True)
    param = {"serviceName": "s"}
    assert await client.register_instance(param) is True
    client._raw.register_instance.assert_awaited_once_with(param)


async def test_deregister_and_update_forward(client) -> None:
    client._raw = AsyncMock()
    for method in ("deregister_instance", "update_instance"):
        setattr(client._raw, method, AsyncMock(return_value=True))
    p = {"serviceName": "s"}
    assert await client.deregister_instance(p) is True
    assert await client.update_instance(p) is True
    client._raw.deregister_instance.assert_awaited_once_with(p)
    client._raw.update_instance.assert_awaited_once_with(p)


async def test_batch_register_deregister_forward(client) -> None:
    client._raw = AsyncMock()
    for m in ("batch_register_instances", "batch_deregister_instances"):
        setattr(client._raw, m, AsyncMock(return_value=True))
    p = [{"serviceName": "s"}]
    assert await client.batch_register_instances(p) is True
    assert await client.batch_deregister_instances(p) is True
    client._raw.batch_register_instances.assert_awaited_once_with(p)
    client._raw.batch_deregister_instances.assert_awaited_once_with(p)


async def test_get_and_list_forward(client) -> None:
    client._raw = AsyncMock()
    for m in ("get_service", "list_services", "list_instances"):
        setattr(client._raw, m, AsyncMock(return_value={"x": 1}))
    p = {"serviceName": "s"}
    assert await client.get_service(p) == {"x": 1}
    assert await client.list_services(p) == {"x": 1}
    assert await client.list_instances(p) == {"x": 1}
    client._raw.get_service.assert_awaited_once_with(p)
    client._raw.list_services.assert_awaited_once_with(p)
    client._raw.list_instances.assert_awaited_once_with(p)


async def test_subscribe_unsubscribe_forward(client) -> None:
    client._raw = AsyncMock()
    for m in ("subscribe", "unsubscribe"):
        setattr(client._raw, m, AsyncMock(return_value=None))
    p = {"serviceName": "s"}
    await client.subscribe(p)
    await client.unsubscribe(p)
    client._raw.subscribe.assert_awaited_once_with(p)
    client._raw.unsubscribe.assert_awaited_once_with(p)


async def test_health_check_forwards_to_server_health() -> None:
    c = NacosNamingClient(server_addr="x", namespace="public")
    c._raw = AsyncMock()
    c._raw.server_health = AsyncMock(return_value=True)
    assert await c.health_check() is True
    c._raw.server_health.assert_awaited_once()


async def test_health_check_false_when_disconnected(client) -> None:
    assert await client.health_check() is False
