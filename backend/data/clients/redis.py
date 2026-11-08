"""Redis 异步客户端对象（redis.asyncio）。

读写日志：redis.asyncio 的所有命令最终都走 execute_command，因此用 LoggedRedis
子类在此处统一打 debug 日志，业务侧（memory / session / 提示词缓存 / 看板 /
配置刷新）无需改动即可全覆盖。
"""
from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from redis.asyncio import Redis

from backend.common.logger import brief, brief_args, logger
from backend.data.clients.base import BaseClient, ClientError

if TYPE_CHECKING:
    from backend.config.schemas import RedisSettings


class LoggedRedis(Redis):
    """在唯一命令入口记录读写 debug 日志的 Redis 客户端。"""

    async def execute_command(self, *args: Any, **options: Any) -> Any:
        cmd = str(args[0]).upper() if args else "UNKNOWN"
        logger.debug(f"[redis] → {cmd} args={brief_args(args[1:], options)}")
        started = time.perf_counter()
        try:
            result = await super().execute_command(*args, **options)
        except Exception as exc:
            cost = (time.perf_counter() - started) * 1000
            logger.debug(f"[redis] ✗ {cmd} cost={cost:.1f}ms error={brief(str(exc))}")
            raise
        cost = (time.perf_counter() - started) * 1000
        logger.debug(f"[redis] ← {cmd} cost={cost:.1f}ms result={brief(result)}")
        return result


class RedisClient(BaseClient):
    """Redis 异步客户端。"""

    name = "redis"

    def __init__(self, url: str, *, decode_responses: bool = True) -> None:
        self._url = url
        self._decode_responses = decode_responses
        self._client: LoggedRedis | None = None

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
            # from_url 内部用 cls(...) 构造，故返回的正是 LoggedRedis 实例
            self._client = LoggedRedis.from_url(
                self._url, decode_responses=self._decode_responses
            )

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
