"""PostgreSQL 客户端对象（engine + sessionmaker，实例内缓存）。

与旧实现的关键差异：
- url 由调用方显式传入（旧版隐式读 app_state.settings）→ 可同时持有多个实例（多库 / 灰度）；
- engine 与 sessionmaker 缓存于实例内（旧版是模块级全局），close 后不会静默重建。
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from backend.data.clients.base import BaseClient, ClientError

if TYPE_CHECKING:
    from backend.config.schemas import PostgresSettings


class PostgresClient(BaseClient):
    """PostgreSQL 异步引擎客户端。"""

    name = "postgres"

    def __init__(self, url: str, *, echo: bool = False) -> None:
        self._url = url
        self._echo = echo
        self._engine: AsyncEngine | None = None
        self._sessionmaker: async_sessionmaker[AsyncSession] | None = None

    @classmethod
    def from_settings(cls, cfg: "PostgresSettings", *, echo: bool = False) -> "PostgresClient":
        """按配置构造（配置由调用方读取并传入，保持本类无全局依赖）。"""
        return cls(cfg.async_url, echo=echo)

    # ---------- 生命周期 ----------
    @property
    def is_connected(self) -> bool:
        return self._engine is not None

    async def connect(self) -> None:
        """创建 engine（幂等）。"""
        if self._engine is None:
            self._engine = create_async_engine(self._url, echo=self._echo, future=True)
            self._sessionmaker = async_sessionmaker(self._engine, expire_on_commit=False)

    async def close(self) -> None:
        """释放 engine（幂等）。"""
        if self._engine is not None:
            await self._engine.dispose()
        self._engine = None
        self._sessionmaker = None

    async def health_check(self) -> bool:
        """真实探活（SELECT 1），未连接返回 False。"""
        if self._engine is None:
            return False
        async with self._engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True

    # ---------- 能力 ----------
    @property
    def engine(self) -> AsyncEngine:
        if self._engine is None:
            raise ClientError("PostgresClient 未连接，请先 await connect()")
        return self._engine

    @property
    def raw(self) -> AsyncEngine:
        return self.engine

    @property
    def sessionmaker(self) -> async_sessionmaker[AsyncSession]:
        if self._sessionmaker is None:
            raise ClientError("PostgresClient 未连接，请先 await connect()")
        return self._sessionmaker

    @asynccontextmanager
    async def session_scope(self) -> AsyncIterator[AsyncSession]:
        """事务作用域会话。"""
        async with self.sessionmaker() as session:
            yield session
