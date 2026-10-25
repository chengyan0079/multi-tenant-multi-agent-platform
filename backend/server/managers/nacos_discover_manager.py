"""NacosDiscoverManager：服务注册 + 注销（仅服务发现，不做配置中心）。

适配 Nacos 3.x + nacos-sdk-python 2.0+（v2.nacos 全异步）：
  - 注册 register_instance(ephemeral=True)，心跳由 SDK gRPC 长连接自动维持。
  - 注销 deregister_instance + shutdown。
放在最后注册（order 110）：确保服务已真正监听后再对外暴露。

服务发现实例由 `NacosClient` 持有（与配置中心 manager 共享同一个容器实例），
本 manager 只负责注册/注销编排与生命周期。
"""
from __future__ import annotations

from backend.app_state import app_state
from backend.common.logger import logger
from backend.config import config
from backend.data.clients.nacos import NacosClient
from backend.server.base_manager import BaseManager, HealthInfo


class NacosDiscoverManager(BaseManager):
    """Nacos 服务发现启动项。"""

    def __init__(self) -> None:
        super().__init__()
        self._client: NacosClient | None = None
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
        client = app_state.clients.ensure(
            "nacos", lambda: NacosClient.from_settings(config.nacos)
        )
        await client.connect()
        self._client = client
        # SDK 缺失或未连接时 naming 为 None（connect 内已告警），跳过注册
        self._naming = client.naming
        if self._naming is None:
            return
        try:
            from v2.nacos import RegisterInstanceParam
        except ImportError:
            return

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
            await self._safe_shutdown()
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
        if self._client is not None:
            await self._client.close()
        self._naming = None
        self._client = None

    async def health(self) -> HealthInfo:
        if not config.nacos.enabled:
            return HealthInfo(status="running", detail="Nacos 未启用，跳过")
        if self._client is None:
            return HealthInfo(status="down", detail="Nacos 客户端未连接")
        if self._registered:
            return HealthInfo(status="running")
        return HealthInfo(status="degraded", detail="已连接但未注册")
