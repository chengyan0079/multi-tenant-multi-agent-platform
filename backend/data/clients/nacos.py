"""Nacos 客户端对象：三条链路的统一入口。

- 配置中心 REST 直连：`ConfigCenterClient`（common/config_center/nacos_config.py）
- 配置中心 SDK 订阅：`ConfigCenterLoader`（common/config_center/loader.py）
- 服务发现：`NacosNamingService`（本对象持有，创建逻辑原先在 manager 内）

前两条复用既有模块的单例（它们已实现软依赖降级），此处仅统一挂载以免重复实现；
服务发现是本对象自身管理的实例，close 后不再静默重建。
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from backend.common.config_center.loader import get_config_center_loader
from backend.common.config_center.nacos_config import get_config_center_client
from backend.common.logger import logger
from backend.common.nacos_compat import import_error_hint, normalize_namespace_id
from backend.data.clients.base import BaseClient

if TYPE_CHECKING:
    from backend.config.schemas import NacosSettings


class NacosClient(BaseClient):
    """Nacos 服务发现 + 配置中心入口。"""

    name = "nacos"

    def __init__(self, server_addr: str, namespace: str) -> None:
        self._server_addr = server_addr
        self._namespace = namespace
        self._naming: Any | None = None

    @classmethod
    def from_settings(cls, cfg: "NacosSettings") -> "NacosClient":
        return cls(server_addr=cfg.server_addr, namespace=cfg.namespace)

    # ---------- 生命周期 ----------
    @property
    def is_connected(self) -> bool:
        return self._naming is not None

    async def connect(self) -> None:
        """创建服务发现实例；SDK 缺失时保持 None（已告警），由调用方决定是否阻断。"""
        if self._naming is not None:
            return
        try:
            from v2.nacos import ClientConfig, NacosNamingService
        except ImportError:
            logger.warning(import_error_hint("Nacos 服务发现"))
            return
        cc = ClientConfig(
            server_addresses=self._server_addr,
            namespace_id=normalize_namespace_id(self._namespace),
        )
        self._naming = await NacosNamingService.create_naming_service(cc)

    async def close(self) -> None:
        """关闭服务发现实例（注销实例由调用方先执行）。"""
        if self._naming is None:
            return
        try:
            await self._naming.shutdown()
        except Exception:  # noqa: BLE001 - 关闭异常不影响进程退出
            pass
        self._naming = None

    # ---------- 能力 ----------
    @property
    def naming(self) -> Any | None:
        """服务发现实例（SDK 缺失或未连接时为 None）。"""
        return self._naming

    @property
    def raw(self) -> Any | None:
        return self._naming

    @property
    def config_center_client(self):
        """配置中心 REST 客户端（复用既有单例）。"""
        return get_config_center_client()

    @property
    def loader(self):
        """配置中心热加载订阅器（复用既有单例）。"""
        return get_config_center_loader()
