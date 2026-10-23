"""NacosDiscoverManager：服务注册 + 注销（仅服务发现，不做配置中心）。

适配 Nacos 3.x + nacos-sdk-python 2.0+（v2.nacos 全异步）：
  - 注册 register_instance(ephemeral=True)，心跳由 SDK gRPC 长连接自动维持。
  - 注销 deregister_instance + shutdown。
放在最后注册（order 110）：确保服务已真正监听后再对外暴露。
"""
from __future__ import annotations

from backend.app_state import app_state
from backend.common.logger import logger
from backend.common.nacos_compat import import_error_hint, normalize_namespace_id
from backend.config import config
from backend.server.base_manager import BaseManager


class NacosDiscoverManager(BaseManager):
    """Nacos 服务发现启动项。"""

    def __init__(self) -> None:
        self._naming = None
        self._registered = False

    @property
    def is_registered(self) -> bool:
        return self._registered

    async def start(self) -> None:
        if not config.nacos.enabled:
            logger.info("Nacos 未启用（NACOS_ENABLED=False），跳过注册")
            return
        app_state.nacos_discovery = self
        try:
            from v2.nacos import ClientConfig, NacosNamingService, RegisterInstanceParam
        except ImportError:
            logger.warning(import_error_hint("Nacos 服务发现"))
            return

        cc = ClientConfig(
            server_addresses=config.nacos.server_addr,
            namespace_id=normalize_namespace_id(config.nacos.namespace),
        )
        self._naming = await NacosNamingService.create_naming_service(cc)
        try:
            ok = await self._naming.register_instance(RegisterInstanceParam(
                service_name=config.service.name,
                ip=config.service.ip,
                port=config.service.port,
                group_name=config.nacos.group,
                ephemeral=True,
            ))
            if not ok:
                raise RuntimeError("register_instance 返回 False")
        except Exception as e:  # 注册是可旁路能力，默认不阻断启动
            if config.nacos.discover_strict:
                raise
            logger.warning(
                f"Nacos 服务注册失败（{e}），跳过注册：服务继续启动，"
                f"但网关无法发现本实例（需阻断启动设 NACOS_DISCOVER_STRICT=True）")
            await self._safe_shutdown()
            return
        self._registered = True
        logger.info(f"Nacos 注册成功: {config.service.name}@{config.service.ip}:{config.service.port}")

    async def stop(self) -> None:
        self._registered = False
        app_state.nacos_discovery = None
        if self._naming is None:
            return
        try:
            from v2.nacos import DeregisterInstanceParam

            await self._naming.deregister_instance(DeregisterInstanceParam(
                service_name=config.service.name, ip=config.service.ip,
                port=config.service.port, group_name=config.nacos.group, ephemeral=True,
            ))
        except Exception:
            logger.warning("Nacos 注销失败（临时实例会随心跳超时自动摘除）")
        await self._safe_shutdown()

    async def _safe_shutdown(self) -> None:
        if self._naming is None:
            return
        try:
            await self._naming.shutdown()
        except Exception:
            pass
        self._naming = None
