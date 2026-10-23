"""RedisManager（order=20）：建立 Redis 异步连接，注入 app_state.redis。"""
from __future__ import annotations

from redis.asyncio import Redis

from backend.app_state import app_state
from backend.common.logger import logger
from backend.server.base_manager import BaseManager


class RedisManager(BaseManager):
    async def start(self) -> None:
        # url 已含密码（RedisSettings.url 把 password 拼进 userinfo 段）
        app_state.redis = Redis.from_url(app_state.settings.redis.url, decode_responses=True)
        # ping 验证连通性，连不上会抛异常，由 AppServer 触发停止回滚
        await app_state.redis.ping()
        logger.info("Redis 连接就绪")

    async def stop(self) -> None:
        if app_state.redis is not None:
            await app_state.redis.aclose()
            app_state.redis = None
