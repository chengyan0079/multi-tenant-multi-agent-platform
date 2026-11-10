"""Nacos 服务发现客户端：遵循 BaseClient 契约，SDK 缺失时软降级。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from backend.common.logger import logger
from backend.common.nacos_compat import import_error_hint, normalize_namespace_id
from backend.data.clients.base import BaseClient, ClientError

if TYPE_CHECKING:
    from v2.nacos import NacosNamingService


class NacosNamingClient(BaseClient):
    """Nacos 服务发现（注册/注销/订阅/查询）。"""

    name = "nacos_naming"

    def __init__(
        self,
        server_addr: str,
        namespace: str,
        user: str = "",
        password: str = "",
        access_key: str = "",
        secret_key: str = "",
    ) -> None:
        self._server_addr = server_addr
        # public -> 空串（Nacos 公共命名空间 id 为空），其余原样（UUID）
        self._namespace = normalize_namespace_id(namespace)
        self._user = user or ""
        self._password = password or ""
        self._access_key = access_key or ""
        self._secret_key = secret_key or ""
        self._raw: "NacosNamingService | None" = None

    @classmethod
    def from_settings(cls, cfg: Any) -> "NacosNamingClient":
        return cls(
            server_addr=cfg.server_addr,
            namespace=cfg.namespace,
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
            from v2.nacos import ClientConfig, NacosNamingService
        except ImportError:
            logger.exception(import_error_hint("Nacos 服务发现"))
            return
        cc = ClientConfig(
            server_addresses=self._server_addr,
            namespace_id=self._namespace,
            username=self._user or None,
            password=self._password or None,
            access_key=self._access_key or None,
            secret_key=self._secret_key or None,
        )
        self._raw = await NacosNamingService.create_naming_service(cc)

    async def close(self) -> None:
        if self._raw is None:
            return
        try:
            await self._raw.shutdown()
        except Exception:  # noqa: BLE001 - 关闭异常不影响进程退出
            pass
        self._raw = None

    @property
    def raw(self) -> "NacosNamingService":
        if self._raw is None:
            raise ClientError("Nacos 服务发现未连接")
        return self._raw

    async def health_check(self) -> bool:
        if not self.is_connected:
            return False
        try:
            return await self._raw.server_health()
        except Exception:  # noqa: BLE001
            return False

    # ---------- 能力（薄转发，请求参数由调用方构建 SDK Param） ----------
    async def register_instance(self, param: Any) -> bool:
        return await self.raw.register_instance(param)

    async def deregister_instance(self, param: Any) -> bool:
        return await self.raw.deregister_instance(param)

    async def update_instance(self, param: Any) -> bool:
        return await self.raw.update_instance(param)

    async def batch_register_instances(self, param: Any) -> bool:
        return await self.raw.batch_register_instances(param)

    async def batch_deregister_instances(self, param: Any) -> bool:
        return await self.raw.batch_deregister_instances(param)

    async def get_service(self, param: Any):
        return await self.raw.get_service(param)

    async def list_services(self, param: Any):
        return await self.raw.list_services(param)

    async def list_instances(self, param: Any):
        return await self.raw.list_instances(param)

    async def subscribe(self, param: Any) -> None:
        await self.raw.subscribe(param)

    async def unsubscribe(self, param: Any) -> None:
        await self.raw.unsubscribe(param)
