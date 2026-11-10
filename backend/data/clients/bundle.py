"""客户端容器：显式持有各中间件客户端，统一装配与释放。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable, Iterator, TypeVar

from backend.common.logger import logger
from backend.data.clients.base import BaseClient

if TYPE_CHECKING:  # 仅类型检查期导入，避免把软依赖 SDK 牵引进容器
    pass

T = TypeVar("T", bound=BaseClient)


class ClientBundle:
    """按名字持有客户端实例的显式容器（进程内默认单例，但可整体替换以便测试）。"""

    def __init__(self) -> None:
        self._clients: dict[str, BaseClient] = {}

    # ---------- 注册 / 取用 ----------
    def add(self, client: T) -> T:
        """注册客户端；重名视为装配错误（避免静默覆盖）。"""
        if not client.name:
            raise ValueError(f"客户端 {type(client).__name__} 未声明 name")
        if client.name in self._clients:
            raise ValueError(f"客户端已注册: {client.name}")
        self._clients[client.name] = client
        return client

    def ensure(self, name: str, factory: Callable[[], T]) -> T:
        """已注册则返回，否则用 factory 创建并注册（manager 重启/重入幂等）。"""
        existing = self._clients.get(name)
        if existing is not None:
            return existing  # type: ignore[return-value]
        client = factory()
        if client.name != name:
            raise ValueError(f"工厂产出的客户端 name={client.name!r} 与注册键 {name!r} 不一致")
        return self.add(client)

    def get(self, name: str) -> BaseClient:
        try:
            return self._clients[name]
        except KeyError:
            raise KeyError(f"未注册的客户端: {name!r}；已注册={sorted(self._clients)}") from None

    def get_as(self, name: str, cls: type[T]) -> T:
        """按期望类型取用，类型不符时明确报错。"""
        client = self.get(name)
        if not isinstance(client, cls):
            raise TypeError(f"客户端 {name!r} 类型为 {type(client).__name__}，期望 {cls.__name__}")
        return client

    def has(self, name: str) -> bool:
        return name in self._clients

    def names(self) -> list[str]:
        return sorted(self._clients)

    def __contains__(self, name: object) -> bool:
        return name in self._clients

    def __iter__(self) -> Iterator[BaseClient]:
        return iter(self._clients.values())

    def __len__(self) -> int:
        return len(self._clients)

    # ---------- 生命周期 ----------
    async def aclose_all(self) -> None:
        """逆序释放全部客户端；单项失败只告警，不影响其余释放。"""
        for name in reversed(list(self._clients)):
            client = self._clients.pop(name, None)
            if client is None:
                continue
            try:
                await client.close()
            except Exception as e:  # noqa: BLE001
                logger.exception(f"客户端 {name} 释放异常: {e}")
