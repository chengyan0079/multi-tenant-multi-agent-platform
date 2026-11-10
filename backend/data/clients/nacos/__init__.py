"""Nacos 客户端封装包：naming/config/ai 三块独立封装，对外聚合为 NacosClient。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from backend.data.clients.base import BaseClient
from backend.data.clients.nacos.ai import NacosAIClient
from backend.data.clients.nacos.config import NacosConfigClient
from backend.data.clients.nacos.naming import NacosNamingClient

if TYPE_CHECKING:
    pass

__all__ = [
    "NacosNamingClient",
    "NacosConfigClient",
    "NacosAIClient",
    "NacosClient",
]


class NacosClient(BaseClient):
    """兼容旧调用方的聚合客户端（服务发现 + 配置中心）。

    仅管理服务发现的生命周期；配置热加载与 REST 客户端各自独立管理。
    """

    name = "nacos"

    def __init__(self, naming: NacosNamingClient) -> None:
        self._naming = naming

    @classmethod
    def from_settings(cls, cfg: Any) -> "NacosClient":
        return cls(NacosNamingClient.from_settings(cfg))

    # ---------- 生命周期（仅服务发现） ----------
    @property
    def is_connected(self) -> bool:
        return self._naming.is_connected

    async def connect(self) -> None:
        await self._naming.connect()

    async def close(self) -> None:
        await self._naming.close()

    @property
    def raw(self):
        return self._naming.raw

    @property
    def naming(self):
        """SDK NacosNamingService 实例（未连接时抛 ClientError）。"""
        return self._naming.raw

    # ---------- 配置中心（保持旧接口，manager 零改动） ----------
    @property
    def loader(self):
        """配置中心热加载单例（SDK gRPC 订阅）。"""
        from backend.common.config_center.loader import get_config_center_loader

        return get_config_center_loader()

    @property
    def config(self) -> NacosConfigClient:
        """SDK 配置中心封装（NacosConfigClient）。"""
        from backend.config import config as app_config

        return NacosConfigClient.from_settings(app_config.nacos_config)

    @property
    def config_center_client(self):
        """REST 客户端（仅用于 SDK 未暴露的列表/历史）。"""
        from backend.common.config_center import get_config_center_client

        return get_config_center_client()
