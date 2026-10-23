"""LangGraph checkpointer：AsyncPostgresSaver.setup() 自动建表，状态外置。"""
from __future__ import annotations

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from backend.app_state import app_state
from backend.server.base_manager import BaseManager


class CheckpointerManager(BaseManager):
    async def start(self) -> None:
        # setup 幂等建表；依赖 PostgreSQLManager 先就绪（order 30 < 35）
        app_state.checkpointer = await AsyncPostgresSaver.setup(app_state.db_engine)

    async def stop(self) -> None:
        if app_state.checkpointer is not None:
            await app_state.checkpointer.aclose()
            app_state.checkpointer = None
