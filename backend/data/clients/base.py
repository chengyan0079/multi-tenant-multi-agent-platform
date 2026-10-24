"""中间件客户端统一契约（替代此前的模块级隐式单例）。

为什么要对象化：
- 构造参数显式传入，不再隐式读 `app_state.settings` → 支持多实例（多库、灰度、多租户分库）；
- 生命周期在实例内部（`connect` / `close` / `is_connected`）→ close 后不会静默重建；
- 可在测试中注入 fake 实例，单测互不污染；
- 统一 `health_check`，便于健康检查与启动探活复用。

约定：
- `name` 为容器中的唯一键；
- `raw` 返回底层 SDK 对象，未连接时抛 `RuntimeError`（而非返回半开实例）；
- `close()` 必须幂等。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar


class ClientError(RuntimeError):
    """客户端未就绪 / 生命周期使用错误。"""


class BaseClient(ABC):
    """中间件客户端基类。"""

    name: ClassVar[str] = ""

    # ---------- 生命周期 ----------
    @abstractmethod
    async def connect(self) -> None:
        """建立连接（幂等）。"""

    @abstractmethod
    async def close(self) -> None:
        """释放连接（幂等），close 后可再次 connect。"""

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """是否已建立连接。"""

    # ---------- 能力 ----------
    @property
    def raw(self) -> Any:
        """底层 SDK 对象（子类覆盖以给出精确类型）。"""
        raise NotImplementedError

    async def health_check(self) -> bool:
        """健康检查；默认以连接态为准，子类可覆盖为真实探活。"""
        return self.is_connected

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return f"<{type(self).__name__} name={self.name!r} connected={self.is_connected}>"
