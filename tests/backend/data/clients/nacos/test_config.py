"""NacosConfigClient 单元测试（SDK 与 OpenAPI 兜底均 mock，不连真 Nacos）。

覆盖：
- SDK 原生 get/publish/remove 转发 + 异常转译（NacosException → None / ConfigCenterError）；
- OpenAPI 兜底 get_config_info / list_configs / list_history / get_history 的解析、空值、错误抛错；
- 命名空间解析（UUID 直出 / 显示名解析 / 缓存）；
- get_config_center_client 单例与未启用抛错。
"""
from __future__ import annotations

import hashlib
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from backend.data.clients.base import ClientError
from backend.data.clients.nacos import NacosConfigClient
from backend.data.clients.nacos.config import ConfigCenterError, get_config_center_client
from v2.nacos import ConfigParam, NacosException


class FakeResp:
    """最小 requests.Response 替身，支持 status_code / text / json。"""

    def __init__(self, payload: Any = None, *, status_code: int = 200, text: str | None = None):
        self.status_code = status_code
        self._payload = payload
        self._text = text

    @property
    def text(self) -> str:
        if self._text is not None:
            return self._text
        import json

        return json.dumps(self._payload)

    def json(self):
        import json

        if self._text is not None:
            return json.loads(self._text)
        return self._payload


@pytest.fixture
def client() -> NacosConfigClient:
    return NacosConfigClient(
        server_addr="http://localhost:8848",
        namespace="3d523e88-a17f-4a90-88c5-d31793405818",
        group="SYSTEM",
    )


# ---------------- SDK 原生（get / publish / remove） ----------------


async def test_get_config_forwards_to_sdk_and_returns_content(client) -> None:
    client._raw = AsyncMock()
    client._raw.get_config = AsyncMock(return_value="hello")
    content = await client.get_config("app.yml", "SYSTEM")
    assert content == "hello"
    arg = client._raw.get_config.call_args.args[0]
    assert isinstance(arg, ConfigParam)
    assert arg.data_id == "app.yml"
    assert arg.group == "SYSTEM"


async def test_get_config_returns_none_on_nacos_exception(client) -> None:
    client._raw = AsyncMock()
    client._raw.get_config = AsyncMock(side_effect=NacosException("not found"))
    assert await client.get_config("app.yml") is None


async def test_publish_config_forwards_with_type_and_cas(client) -> None:
    client._raw = AsyncMock()
    client._raw.publish_config = AsyncMock(return_value=True)
    ok = await client.publish_config(
        "app.yml", "c", "SYSTEM", content_format="yaml", cas_md5="abc"
    )
    assert ok is True
    arg = client._raw.publish_config.call_args.args[0]
    assert arg.data_id == "app.yml"
    assert arg.group == "SYSTEM"
    assert arg.content == "c"
    assert arg.type == "yaml"
    assert arg.cas_md5 == "abc"


async def test_publish_config_raises_config_center_error_on_failure(client) -> None:
    client._raw = AsyncMock()
    client._raw.publish_config = AsyncMock(side_effect=NacosException("boom"))
    with pytest.raises(ConfigCenterError):
        await client.publish_config("app.yml", "c")


async def test_remove_config_forwards_with_cas(client) -> None:
    client._raw = AsyncMock()
    client._raw.remove_config = AsyncMock(return_value=True)
    ok = await client.remove_config("app.yml", "SYSTEM", cas_md5="abc")
    assert ok is True
    arg = client._raw.remove_config.call_args.args[0]
    assert arg.data_id == "app.yml"
    assert arg.cas_md5 == "abc"


async def test_remove_config_raises_config_center_error_on_failure(client) -> None:
    client._raw = AsyncMock()
    client._raw.remove_config = AsyncMock(side_effect=NacosException("boom"))
    with pytest.raises(ConfigCenterError):
        await client.remove_config("app.yml")


async def test_get_config_auto_connects_when_raw_none(client) -> None:
    fake_raw = AsyncMock()
    fake_raw.get_config = AsyncMock(return_value="auto")
    captured: dict = {}

    async def fake_create(cc):
        captured["cc"] = cc
        return fake_raw

    with patch("v2.nacos.NacosConfigService.create_config_service", new=fake_create):
        content = await client.get_config("app.yml")
    assert content == "auto"
    # 鉴权透传：未设 user/password 应为 None；namespace 原样传递
    assert captured["cc"].username is None
    assert captured["cc"].namespace_id == "3d523e88-a17f-4a90-88c5-d31793405818"


# ---------------- OpenAPI 兜底 ----------------


async def test_get_config_info_parses_payload(client) -> None:
    resp = FakeResp({
        "code": 0,
        "data": {"content": "x", "type": "yaml", "md5": "m", "createTime": 1, "modifyTime": 2},
    })
    with patch("backend.data.clients.nacos.config.requests.get", return_value=resp):
        info = await client.get_config_info("app.yml", "SYSTEM")
    assert info == {
        "content": "x", "type": "yaml", "md5": "m", "createTime": 1, "modifyTime": 2,
    }


async def test_get_config_info_returns_none_when_404() -> None:
    c = NacosConfigClient(server_addr="x", namespace="3d523e88-a17f-4a90-88c5-d31793405818")
    with patch(
        "backend.data.clients.nacos.config.requests.get",
        return_value=FakeResp(status_code=404),
    ):
        assert await c.get_config_info("app.yml") is None


async def test_get_config_info_returns_none_when_code_20004() -> None:
    c = NacosConfigClient(server_addr="x", namespace="3d523e88-a17f-4a90-88c5-d31793405818")
    with patch(
        "backend.data.clients.nacos.config.requests.get",
        return_value=FakeResp({"code": 20004, "message": "not found"}),
    ):
        assert await c.get_config_info("app.yml") is None


async def test_get_config_info_raises_on_business_error(client) -> None:
    resp = FakeResp({"code": 500, "message": "bad", "data": None})
    with patch("backend.data.clients.nacos.config.requests.get", return_value=resp):
        with pytest.raises(ConfigCenterError):
            await client.get_config_info("app.yml")


async def test_list_configs_parses_page_items(client) -> None:
    resp = FakeResp({
        "code": 0,
        "data": {"pageItems": [{"dataId": "a", "groupName": "SYSTEM"}], "totalCount": 1},
    })
    with patch("backend.data.clients.nacos.config.requests.get", return_value=resp):
        data = await client.list_configs(group="SYSTEM", page_size=10)
    assert data["pageItems"] == [{"dataId": "a", "groupName": "SYSTEM"}]


async def test_list_configs_with_meta_fills_per_item(client) -> None:
    list_resp = FakeResp({"code": 0, "data": {"pageItems": [{"dataId": "a", "groupName": "SYSTEM"}]}})
    detail = {"code": 0, "data": {"content": "x", "type": "yaml", "md5": "m", "createTime": 1, "modifyTime": 2}}
    with patch(
        "backend.data.clients.nacos.config.requests.get",
        side_effect=[list_resp, FakeResp(detail)],
    ):
        data = await client.list_configs(group="SYSTEM", with_meta=True)
    item = data["pageItems"][0]
    assert item["type"] == "yaml"
    assert item["md5"] == "m"
    assert item["lastModified"] == 2


async def test_list_configs_overwrites_zero_times_from_detail(client) -> None:
    """Nacos 3.x 列表把时间返回为 0，必须用详情真实值覆盖，否则前端渲染成 1970。"""
    list_resp = FakeResp(
        {
            "code": 0,
            "data": {
                "pageItems": [
                    {"dataId": "a", "groupName": "SYSTEM", "createTime": 0, "modifyTime": 0}
                ]
            },
        }
    )
    detail = {
        "code": 0,
        "data": {"content": "x", "createTime": 1793992898000, "modifyTime": 1793992900000},
    }
    with patch(
        "backend.data.clients.nacos.config.requests.get",
        side_effect=[list_resp, FakeResp(detail)],
    ):
        data = await client.list_configs(group="SYSTEM", with_meta=True)
    item = data["pageItems"][0]
    assert item["createTime"] == 1793992898000
    assert item["modifyTime"] == 1793992900000
    assert item["lastModified"] == 1793992900000


async def test_list_history_normalizes_nid_and_time() -> None:
    c = NacosConfigClient(server_addr="x", namespace="3d523e88-a17f-4a90-88c5-d31793405818")
    list_resp = FakeResp({"code": 0, "data": {"pageItems": [{"id": 99, "lastModifiedTime": 5}]}})
    detail = {"code": 0, "data": {"content": "body", "md5": "d4"}}
    with patch(
        "backend.data.clients.nacos.config.requests.get",
        side_effect=[list_resp, FakeResp(detail)],
    ):
        data = await c.list_history("app.yml", "SYSTEM")
    it = data["pageItems"][0]
    assert it["nid"] == 99
    assert it["createdTime"] == 5
    assert it["md5"] == "d4"  # 详情带的 md5 直接采用


async def test_list_history_computes_md5_from_content() -> None:
    c = NacosConfigClient(server_addr="x", namespace="3d523e88-a17f-4a90-88c5-d31793405818")
    list_resp = FakeResp({"code": 0, "data": {"pageItems": [{"id": 7, "lastModifiedTime": 5}]}})
    detail = {"code": 0, "data": {"content": "hello"}}
    with patch(
        "backend.data.clients.nacos.config.requests.get",
        side_effect=[list_resp, FakeResp(detail)],
    ):
        data = await c.list_history("app.yml", "SYSTEM")
    expected = hashlib.md5("hello".encode("utf-8")).hexdigest()
    assert data["pageItems"][0]["md5"] == expected


async def test_get_history_normalizes_nid() -> None:
    c = NacosConfigClient(server_addr="x", namespace="3d523e88-a17f-4a90-88c5-d31793405818")
    resp = FakeResp({"code": 0, "data": {"id": 42, "content": "c", "lastModifiedTime": 9}})
    with patch("backend.data.clients.nacos.config.requests.get", return_value=resp):
        obj = await c.get_history("app.yml", 42, "SYSTEM")
    assert obj["nid"] == 42
    assert obj["createdTime"] == 9


async def test_login_failure_raises_config_center_error(client) -> None:
    client._user = "nacos"
    client._token = None
    login = FakeResp({"x": 1}, status_code=401)
    with patch("backend.data.clients.nacos.config.requests.post", return_value=login):
        with pytest.raises(ConfigCenterError):
            await client.get_config_info("app.yml")


# ---------------- 命名空间解析 ----------------


def test_ns_id_returns_uuid_directly(client) -> None:
    # 已是 UUID，不应触发 HTTP 命名空间查询
    assert client._ns_id() == "3d523e88-a17f-4a90-88c5-d31793405818"


def test_ns_id_resolves_display_name() -> None:
    c = NacosConfigClient(server_addr="x", namespace="agent-platform")
    ns_resp = FakeResp([{"namespaceShowName": "agent-platform", "namespace": "uuid-123"}])
    with patch("backend.data.clients.nacos.config.requests.get", return_value=ns_resp):
        assert c._ns_id() == "uuid-123"
    # 二次调用走缓存，不应再发请求
    with patch(
        "backend.data.clients.nacos.config.requests.get",
        side_effect=AssertionError("不应二次请求"),
    ):
        assert c._ns_id() == "uuid-123"


# ---------------- 单例 ----------------


def test_get_config_center_client_returns_singleton(monkeypatch) -> None:
    import backend.config
    import backend.data.clients.nacos.config as cfg_mod

    monkeypatch.setattr(backend.config.config.nacos_config, "enabled", True)
    cfg_mod._config_client = None
    c1 = get_config_center_client()
    c2 = get_config_center_client()
    assert isinstance(c1, NacosConfigClient)
    assert c1 is c2


def test_get_config_center_client_raises_when_disabled(monkeypatch) -> None:
    import backend.config
    import backend.data.clients.nacos.config as cfg_mod

    monkeypatch.setattr(backend.config.config.nacos_config, "enabled", False)
    cfg_mod._config_client = None
    with pytest.raises(ConfigCenterError):
        get_config_center_client()
