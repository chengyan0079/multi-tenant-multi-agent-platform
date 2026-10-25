"""PostgreSQL 异步引擎（checkpointer + 业务 + 记忆）生命周期。

连接由 `PostgresClient` 封装，本 manager 只负责生命周期：
start 装配实例并注册进 `app_state.clients`，stop 释放。
"""
from __future__ import annotations

from sqlalchemy import text

from backend.app_state import app_state
from backend.data.clients.postgres import PostgresClient
from backend.server.base_manager import BaseManager, HealthInfo


class PostgreSQLManager(BaseManager):
    async def start(self) -> None:
        client = app_state.clients.ensure(
            "postgres", lambda: PostgresClient.from_settings(app_state.settings.postgres)
        )
        await client.connect()
        app_state.db_engine = client.engine

    async def stop(self) -> None:
        if app_state.clients.has("postgres"):
            await app_state.clients.get_as("postgres", PostgresClient).close()
        app_state.db_engine = None

    async def health(self) -> HealthInfo:
        """真实探活：执行 SELECT 1，引擎未初始化或查询失败记为 down。"""
        engine = app_state.db_engine
        if engine is None:
            return HealthInfo(status="down", detail="engine 未初始化")
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            return HealthInfo(status="running", detail="ok")
        except Exception as exc:
            return HealthInfo(status="down", detail=f"{type(exc).__name__}: {exc}")
