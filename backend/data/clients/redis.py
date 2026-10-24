"""Redis 异步客户端对象（redis.asyncio）。"""
from __future__ import annotations

from typing import TYPE_CHECKING

from redis.asyncio import Redis

from backend.data.clients.base import BaseClient, ClientError

if TYPE_CHECKING:
    from backend.config.schemas import RedisSettings


class RedisClient(BaseClient):
    """Redis 异步客户端。"""

    name = "redis"

    def __init__(self, url: str, *, decode_responses: bool = True) -> None:
        self._url = url
        self._decode_responses = decode_responses
        self._client: Redis | None = None

    @classmethod
    def from_settings(cls, cfg: "RedisSettings") -> "RedisClient":
        """按配置构造（url 已含密码，见 RedisSettings.url）。"""
        return cls(cfg.url, decode_responses=True)

    # ---------- 生命周期 ----------
    @property
    def is_connected(self) -> bool:
        return self._client is not None

    async def connect(self) -> None:
        if self._client is None:
            self._client = Redis.from_url(self._url, decode_responses=self._decode_responses)

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
        self._client = None

    async def health_check(self) -> bool:
        """ping 探活，不通抛错由调用方处理。"""
        if self._client is None:
            return False
        await self.ping()
        return True

    # ---------- 能力 ----------
    @property
    def raw(self) -> Redis:
        if self._client is None:
            raise ClientError("RedisClient 未连接，请先 await connect()")
        return self._client

    async def ping(self) -> None:
        """连通性探测（由 manager 在 start 时调用）。"""
        await self.raw.ping()
