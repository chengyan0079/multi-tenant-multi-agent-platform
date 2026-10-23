"""PostgreSQL 异步引擎（checkpointer + 业务 + 记忆）。"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from backend.app_state import app_state
from backend.server.base_manager import BaseManager


class PostgreSQLManager(BaseManager):
    async def start(self) -> None:
        app_state.db_engine: AsyncEngine = create_async_engine(
            app_state.settings.postgres.async_url, echo=False, future=True
        )

    async def stop(self) -> None:
        if app_state.db_engine is not None:
            await app_state.db_engine.dispose()
            app_state.db_engine = None
