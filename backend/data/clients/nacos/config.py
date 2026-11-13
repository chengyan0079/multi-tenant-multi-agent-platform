"""Nacos 配置中心客户端：SDK gRPC 读写，未暴露接口用 OpenAPI 兜底。"""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from typing import TYPE_CHECKING, Any, Callable

import requests

from backend.common.logger import logger
from backend.common.nacos_compat import import_error_hint, normalize_namespace_id
from backend.data.clients.base import BaseClient, ClientError

try:  # SDK 软依赖：缺失时模块仍可加载，调用能力方法时由 raw 守卫抛错
    from v2.nacos import ConfigParam
except ImportError:  # pragma: no cover - SDK 缺失分支
    ConfigParam = None  # type: ignore[assignment]

if TYPE_CHECKING:
    from v2.nacos import NacosConfigService as _ConfigService


class ConfigCenterError(RuntimeError):
    """配置中心调用异常。"""


# Nacos 3.x 列表接口在时间未填充时返回 0（而非缺字段），0 不是合法时间戳
_TIME_KEYS = (
    "createTime",
    "modifyTime",
    "lastModified",
    "lastModifiedTime",
    "createdTime",
    "gmtCreate",
    "gmtModified",
)


def _normalize_times(data: dict[str, Any]) -> dict[str, Any]:
    """把时间字段的 0 / 空串归一为 None，避免前端按 epoch 渲染出 1970。"""
    for key in _TIME_KEYS:
        if key in data and not data[key]:
            data[key] = None
    return data


class NacosConfigClient(BaseClient):
    """Nacos 配置中心（SDK gRPC + OpenAPI 兜底）。"""

    name = "nacos_config"

    def __init__(
        self,
        server_addr: str,
        namespace: str,
        group: str = "DEFAULT_GROUP",
        user: str = "",
        password: str = "",
        access_key: str = "",
        secret_key: str = "",
        timeout: float = 10.0,
    ) -> None:
        self._server_addr = server_addr
        # public -> 空串（Nacos 公共命名空间 id 为空），其余原样（UUID）
        self._namespace = normalize_namespace_id(namespace)
        self._group = group or "DEFAULT_GROUP"
        self._user = user or ""
        self._password = password or ""
        self._access_key = access_key or ""
        self._secret_key = secret_key or ""
        self._timeout = timeout
        self._token: str | None = None
        self._ns_resolved: str | None = None
        self._raw: "_ConfigService | None" = None

    @classmethod
    def from_settings(cls, cfg: Any) -> "NacosConfigClient":
        return cls(
            server_addr=cfg.server_addr,
            namespace=cfg.namespace,
            group=getattr(cfg, "group", "DEFAULT_GROUP") or "DEFAULT_GROUP",
            user=getattr(cfg, "user", "") or "",
            password=getattr(cfg, "password", "") or "",
            access_key=getattr(cfg, "access_key", "") or "",
            secret_key=getattr(cfg, "secret_key", "") or "",
        )

    # ---------- 生命周期 ----------
    @property
    def is_connected(self) -> bool:
        return self._raw is not None

    async def connect(self) -> None:
        if self._raw is not None:
            return
        try:
            from v2.nacos import ClientConfig, NacosConfigService
        except ImportError:
            logger.exception(import_error_hint("Nacos 配置中心"))
            return
        cc = ClientConfig(
            server_addresses=self._server_addr,
            namespace_id=self._namespace,
            username=self._user or None,
            password=self._password or None,
            access_key=self._access_key or None,
            secret_key=self._secret_key or None,
        )
        self._raw = await NacosConfigService.create_config_service(cc)

    async def close(self) -> None:
        if self._raw is None:
            return
        try:
            await self._raw.shutdown()
        except Exception:  # noqa: BLE001
            pass
        self._raw = None

    @property
    def raw(self) -> "_ConfigService":
        if self._raw is None:
            raise ClientError("Nacos 配置中心未连接")
        return self._raw

    async def _ensure_connected(self) -> None:
        """SDK 原生方法调用前惰性建连（首次使用自动连，避免调用方管理生命周期）。"""
        if self._raw is None:
            await self.connect()

    async def health_check(self) -> bool:
        if not self.is_connected:
            return False
        try:
            return await self._raw.server_health()
        except Exception:  # noqa: BLE001
            return False

    # ---------- SDK 原生能力（gRPC） ----------
    async def get_config(self, data_id: str, group: str | None = None) -> str | None:
        await self._ensure_connected()
        from v2.nacos import NacosException

        try:
            return await self._raw.get_config(
                ConfigParam(data_id=data_id, group=group or self._group)
            )
        except NacosException:
            # 配置不存在等按“无内容”处理，与旧 REST 客户端语义一致
            return None

    async def publish_config(
        self,
        data_id: str,
        content: str,
        group: str | None = None,
        content_format: str = "text",
        cas_md5: str | None = None,
    ) -> bool:
        await self._ensure_connected()
        from v2.nacos import NacosException

        try:
            # cas_md5 是 str 字段（非 Optional），未提供时不能传 None，否则 pydantic 校验失败
            kwargs: dict[str, Any] = {
                "data_id": data_id,
                "group": group or self._group,
                "content": content,
                "type": content_format,
            }
            if cas_md5 is not None:
                kwargs["cas_md5"] = cas_md5
            return await self._raw.publish_config(ConfigParam(**kwargs))
        except NacosException as e:
            raise ConfigCenterError(f"Nacos 发布失败: {e}")

    async def remove_config(
        self,
        data_id: str,
        group: str | None = None,
        cas_md5: str | None = None,
    ) -> bool:
        await self._ensure_connected()
        from v2.nacos import NacosException

        try:
            kwargs: dict[str, Any] = {"data_id": data_id, "group": group or self._group}
            if cas_md5 is not None:
                kwargs["cas_md5"] = cas_md5
            return await self._raw.remove_config(ConfigParam(**kwargs))
        except NacosException as e:
            raise ConfigCenterError(f"Nacos 删除失败: {e}")

    async def add_listener(self, data_id: str, group: str, listener: Callable) -> None:
        await self._ensure_connected()
        await self._raw.add_listener(data_id, group or self._group, listener)

    async def remove_listener(self, data_id: str, group: str, listener: Callable) -> None:
        await self._ensure_connected()
        await self._raw.remove_listener(data_id, group or self._group, listener)

    # ---------- OpenAPI 兜底能力（SDK 未暴露的列表/历史/元信息） ----------
    def _base(self) -> str:
        return f"{self._server_addr}/nacos/v3"

    def _path(self, action: str) -> str:
        mapping = {
            "get": "/admin/cs/config",
            "publish": "/admin/cs/config",
            "remove": "/admin/cs/config",
            "list": "/admin/cs/config/list",
            "history": "/admin/cs/history/list",
            "history_detail": "/admin/cs/history",
            "namespaces": "/admin/core/namespace/list",
        }
        return f"{self._base()}{mapping[action]}"

    def _ensure_token(self) -> str | None:
        if self._token or not self._user:
            return self._token
        resp = requests.post(
            f"{self._server_addr}/nacos/v3/auth/login",
            data={"username": self._user, "password": self._password},
            timeout=self._timeout,
        )
        if resp.status_code != 200:
            raise ConfigCenterError(f"Nacos 登录失败: {resp.status_code} {resp.text}")
        self._token = resp.json().get("accessToken")
        if not self._token:
            raise ConfigCenterError("Nacos 登录未返回 accessToken")
        return self._token

    def _auth_header(self) -> dict:
        token = self._ensure_token()
        return {"Authorization": f"Bearer {token}"} if token else {}

    def _ns_id(self) -> str:
        """命名空间显示名 → Nacos namespaceId（UUID）；已是 UUID 则原样返回。"""
        if self._ns_resolved is not None:
            return self._ns_resolved
        try:
            uuid.UUID(self._namespace)
            self._ns_resolved = self._namespace
            return self._ns_resolved
        except ValueError:
            pass
        try:
            resp = requests.get(
                self._path("namespaces"),
                params={},
                headers=self._auth_header(),
                timeout=self._timeout,
            )
            for n in self._check(resp) or []:
                if isinstance(n, dict) and n.get("namespaceShowName") == self._namespace:
                    self._ns_resolved = n["namespace"]
                    return self._ns_resolved
        except Exception:  # noqa: BLE001 - 解析失败回落到原名
            pass
        self._ns_resolved = self._namespace
        return self._ns_resolved

    def _query(self, extra: dict[str, Any]) -> dict[str, Any]:
        params: dict[str, Any] = {"namespaceId": self._ns_id()}
        params.update({k: v for k, v in extra.items() if v is not None})
        return params

    def _check(self, resp: requests.Response) -> Any:
        if resp.status_code != 200:
            raise ConfigCenterError(f"Nacos 返回 {resp.status_code}: {resp.text}")
        text = resp.text.strip()
        if text in ("true", "false"):
            return text == "true"
        try:
            data = resp.json()
        except ValueError:
            return text
        if isinstance(data, dict) and "code" in data:
            if data.get("code") != 0:
                raise ConfigCenterError(
                    f"Nacos 业务错误: {data.get('message')} (code={data.get('code')})"
                )
            payload = data.get("data")
            return payload if payload is not None else True
        return data

    def _rest_get_config_info(self, data_id: str, group: str | None = None) -> dict | None:
        """配置元信息（content/type/md5/时间）；不存在返回 None。"""
        params = self._query({"dataId": data_id, "groupName": group or self._group})
        resp = requests.get(
            self._path("get"),
            params=params,
            headers=self._auth_header(),
            timeout=self._timeout,
        )
        if resp.status_code == 404:
            return None
        try:
            j = resp.json()
        except ValueError:
            text = resp.text.strip()
            return {"content": text} if text else None
        if isinstance(j, dict) and "code" in j:
            if j.get("code") == 0:
                d = j.get("data")
                if isinstance(d, dict):
                    return _normalize_times(d)
                if isinstance(d, str):
                    return {"content": d}
                return None
            if j.get("code") == 20004:
                return None
            raise ConfigCenterError(f"Nacos 查询失败: {j.get('message')} (code={j.get('code')})")
        text = resp.text.strip()
        return {"content": text} if text else None

    async def get_config_info(self, data_id: str, group: str | None = None) -> dict | None:
        return await asyncio.to_thread(self._rest_get_config_info, data_id, group)

    def _fill_config_meta(self, item: dict) -> None:
        """列表项补齐 createTime/modifyTime/type/md5，并统一出 lastModified。

        列表接口的时间常为 0（非缺失字段），故一律按真值判断缺失并允许覆盖。
        """
        if not (item.get("createTime") and item.get("modifyTime")):
            try:
                info = self._rest_get_config_info(
                    item.get("dataId") or "", item.get("groupName") or self._group
                )
            except Exception:  # noqa: BLE001 - 单条回查失败不影响整个列表
                info = None
            if isinstance(info, dict):
                for key in ("createTime", "modifyTime", "type", "md5", "appName"):
                    if not item.get(key) and info.get(key):
                        item[key] = info[key]
        _normalize_times(item)
        if not item.get("lastModified"):
            item["lastModified"] = item.get("modifyTime") or item.get("createTime")

    def _rest_list_configs(
        self,
        data_id: str | None = None,
        group: str | None = None,
        page_no: int = 1,
        page_size: int = 100,
        with_meta: bool = False,
    ) -> dict:
        resp = requests.get(
            self._path("list"),
            params=self._query(
                {
                    "pageNo": page_no,
                    "pageSize": page_size,
                    # group 为空表示跨全部分组；不能回落到 self._group，否则其它 group 的配置会“消失”
                    "groupName": group or "",
                    "dataId": data_id or "",
                }
            ),
            headers=self._auth_header(),
            timeout=self._timeout,
        )
        data = self._check(resp) or {}
        if with_meta and isinstance(data, dict):
            for it in data.get("pageItems") or []:
                if isinstance(it, dict):
                    self._fill_config_meta(it)
        return data

    async def list_configs(
        self,
        data_id: str | None = None,
        group: str | None = None,
        page_no: int = 1,
        page_size: int = 100,
        with_meta: bool = False,
    ) -> dict:
        return await asyncio.to_thread(
            self._rest_list_configs, data_id, group, page_no, page_size, with_meta
        )

    def _rest_list_history(
        self,
        data_id: str,
        group: str | None = None,
        page_no: int = 1,
        page_size: int = 100,
    ) -> dict:
        resp = requests.get(
            self._path("history"),
            params=self._query(
                {
                    "dataId": data_id,
                    "groupName": group or self._group,
                    "pageNo": page_no,
                    "pageSize": page_size,
                }
            ),
            headers=self._auth_header(),
            timeout=self._timeout,
        )
        data = self._check(resp) or {}
        for it in data.get("pageItems") or []:
            if not isinstance(it, dict):
                continue
            # nid：不同 Nacos 版本返回 id 或 nid
            if "nid" not in it and "id" in it:
                it["nid"] = it["id"]
            # 时间：历史列表常见 lastModifiedTime，部分版本为 createdTime
            if not it.get("createdTime"):
                for key in ("lastModifiedTime", "gmtModified", "createTime", "timestamp"):
                    if it.get(key):
                        it["createdTime"] = it[key]
                        break
            # md5：列表接口通常不返回，用详情补齐；详情无 md5 时按内容计算
            if not it.get("md5"):
                nid = it.get("nid")
                detail = None
                if nid is not None:
                    try:
                        detail = self._rest_get_history(data_id, int(nid), group)
                    except Exception:  # noqa: BLE001
                        detail = None
                if isinstance(detail, dict):
                    content = detail.get("content")
                    if detail.get("md5"):
                        it["md5"] = detail["md5"]
                    elif isinstance(content, str) and content:
                        it["md5"] = hashlib.md5(content.encode("utf-8")).hexdigest()
                    if not it.get("createdTime"):
                        it["createdTime"] = detail.get("createdTime") or detail.get(
                            "lastModifiedTime"
                        )
            _normalize_times(it)
        return data

    async def list_history(
        self,
        data_id: str,
        group: str | None = None,
        page_no: int = 1,
        page_size: int = 100,
    ) -> dict:
        return await asyncio.to_thread(self._rest_list_history, data_id, group, page_no, page_size)

    def _rest_get_history(self, data_id: str, nid: int, group: str | None = None) -> dict | None:
        resp = requests.get(
            self._path("history_detail"),
            params=self._query(
                {
                    "dataId": data_id,
                    "groupName": group or self._group,
                    "nid": nid,
                }
            ),
            headers=self._auth_header(),
            timeout=self._timeout,
        )
        data = self._check(resp)
        if isinstance(data, dict):
            # 归一化：详情接口字段名与列表不一致，前端按 nid/createdTime 渲染
            obj = data.get("data") or data
            if isinstance(obj, dict):
                if "nid" not in obj and "id" in obj:
                    obj["nid"] = obj["id"]
                if not obj.get("createdTime"):
                    for key in (
                        "lastModifiedTime",
                        "modifyTime",
                        "gmtModified",
                        "createTime",
                        "timestamp",
                    ):
                        if obj.get(key):
                            obj["createdTime"] = obj[key]
                            break
                return _normalize_times(obj)
        return data

    async def get_history(self, data_id: str, nid: int, group: str | None = None) -> dict | None:
        return await asyncio.to_thread(self._rest_get_history, data_id, nid, group)


# 懒加载单例：替代旧 common/config_center/nacos_config.get_config_center_client
_config_client: "NacosConfigClient | None" = None


def get_config_center_client() -> "NacosConfigClient":
    """懒加载单例客户端（未启用时抛 ConfigCenterError）。"""
    global _config_client
    if _config_client is None:
        from backend.config import config as app_config

        if not app_config.nacos_config.enabled:
            raise ConfigCenterError("Nacos 配置中心未启用（NACOS_CONFIG_ENABLED=False）")
        _config_client = NacosConfigClient.from_settings(app_config.nacos_config)
    return _config_client
