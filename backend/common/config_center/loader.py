"""配置中心热加载：gRPC 长连接订阅 Nacos 变更热更新本地缓存（适配 3.x + sdk 2.0+）。"""

from __future__ import annotations

import asyncio
import json
from typing import Callable, Optional

try:
    import yaml

    _HAS_YAML = True
except ImportError:
    yaml = None  # type: ignore
    _HAS_YAML = False

from backend.common.logger import logger
from backend.common.nacos_compat import import_error_hint, resolve_namespace_id
from backend.config import config as app_config

WatcherCb = Callable[[str, str, Optional[str]], None]  # (data_id, group, content)

_loader: "ConfigCenterLoader | None" = None


class ConfigCenterLoader:
    """配置中心本地缓存 + 热更新（SDK gRPC 长连接订阅）。"""

    def __init__(self) -> None:
        self._client = None
        self._cache: dict[tuple[str, str], str] = {}
        self._started = False

    @property
    def is_started(self) -> bool:
        return self._started

    async def start(self) -> None:
        """连接 Nacos 配置中心（gRPC）；未启用或 SDK 缺失时跳过。"""
        if not app_config.nacos_config.enabled:
            logger.warning("配置中心未启用（NACOS_CONFIG_ENABLED=False），跳过热加载")
            return
        try:
            from v2.nacos import ClientConfig, NacosConfigService
        except ImportError:
            logger.exception(import_error_hint("配置中心热加载"))
            return
        ns_id = await asyncio.to_thread(
            resolve_namespace_id,
            app_config.nacos_config.server_addr,
            app_config.nacos_config.namespace,
            app_config.nacos_config.user,
            app_config.nacos_config.password,
        )
        cc = ClientConfig(
            server_addresses=app_config.nacos_config.server_addr,
            namespace_id=ns_id,
            username=app_config.nacos_config.user or None,
            password=app_config.nacos_config.password or None,
        )
        self._client = await NacosConfigService.create_config_service(cc)
        self._started = True
        logger.info(f"配置中心热加载已启动: ns={app_config.nacos_config.namespace}")

    async def stop(self) -> None:
        if self._client is not None:
            try:
                await self._client.shutdown()
            except Exception:
                pass
        self._cache.clear()
        self._client = None
        self._started = False

    def _key(self, data_id: str, group: str | None) -> tuple[str, str]:
        return (group or app_config.nacos_config.group, data_id)

    async def _on_change(self, tenant: str, group: str, data_id: str, content: str) -> None:
        self._cache[(group, data_id)] = content
        logger.info(f"配置中心热更新: data_id={data_id} group={group}")

    async def get(self, data_id: str, group: str | None = None) -> Optional[str]:
        """读取配置（优先缓存；未命中则从 Nacos 拉取并自动订阅变更）。"""
        key = self._key(data_id, group)
        if key in self._cache:
            return self._cache[key]
        if not self._started or self._client is None:
            return None
        from v2.nacos import ConfigParam, NacosException

        try:
            content = await self._client.get_config(ConfigParam(data_id=data_id, group=key[0]))
        except NacosException as e:
            logger.exception(f"配置中心读取失败: data_id={data_id} err={e}")
            return None
        if not content:
            return None
        self._cache[key] = content
        try:
            await self._client.add_listener(data_id, key[0], self._on_change)
        except NacosException as e:
            logger.exception(f"注册配置监听失败（不影响读取）: data_id={data_id} err={e}")
        return content

    async def get_json(self, data_id: str, group: str | None = None) -> Optional[dict]:
        """按后缀选择解析器：yaml/yml 用 YAML，其余 JSON。"""
        content = await self.get(data_id, group)
        if content is None:
            return None
        ext = data_id.rsplit(".", 1)[-1].lower() if "." in data_id else ""
        if ext in ("yaml", "yml") and _HAS_YAML:
            try:
                return yaml.safe_load(content)  # type: ignore[union-attr]
            except yaml.YAMLError:  # type: ignore[union-attr]
                logger.exception(f"配置非 YAML，无法解析: data_id={data_id}")
                return None
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            logger.exception(f"配置非 JSON，无法解析: data_id={data_id}")
            return None

    async def subscribe(self, data_id: str, group: str | None, callback: WatcherCb) -> None:
        """业务侧主动订阅某配置变更（除缓存外额外回调）。"""
        if not self._started or self._client is None:
            return
        g = group or app_config.nacos_config.group

        async def _adapted(tenant: str, grp: str, did: str, content: str) -> None:
            callback(did, grp, content)

        await self._client.add_listener(data_id, g, _adapted)


def get_config_center_loader() -> ConfigCenterLoader:
    """懒加载单例。"""
    global _loader
    if _loader is None:
        _loader = ConfigCenterLoader()
    return _loader
