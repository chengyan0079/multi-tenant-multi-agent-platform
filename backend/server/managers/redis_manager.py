"""RedisManager（order=20）：建立 Redis 异步连接，注入 app_state.redis。

连接由 `RedisClient` 封装，本 manager 只做生命周期与连通性校验。
"""

from __future__ import annotations

from backend.app_state import app_state
from backend.common.logger import logger
from backend.data.clients.redis import RedisClient
from backend.server.base_manager import BaseManager, HealthInfo


class RedisManager(BaseManager):
    async def startup_stats(self) -> str | None:
        try:
            n = await app_state.redis.dbsize()
            return f"keys={int(n)}"
        except Exception:  # noqa: BLE001 - 统计失败不打印
            return None

    async def start(self) -> None:
        client = app_state.clients.ensure(
            "redis", lambda: RedisClient.from_settings(app_state.settings.redis)
        )
        await client.connect()
        app_state.redis = client.raw
        # ping 验证连通性，连不上会抛异常，由 AppServer 触发停止回滚
        await client.ping()
        logger.info("Redis 连接就绪")

    async def stop(self) -> None:
        if app_state.clients.has("redis"):
            await app_state.clients.get_as("redis", RedisClient).close()
        app_state.redis = None

    async def health(self) -> HealthInfo:
        """真实探活：ping Redis，连不上或客户端未初始化记为 down。"""
        try:
            client = app_state.clients.get_as("redis", RedisClient)
            await client.ping()
            return HealthInfo(status="running", detail="pong")
        except Exception as exc:
            return HealthInfo(status="down", detail=f"{type(exc).__name__}: {exc}")
