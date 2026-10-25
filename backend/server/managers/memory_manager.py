"""记忆存储（短期/长期/语义）。"""
from __future__ import annotations

from backend.app_state import app_state
from backend.common.memory.memory import MemoryStore
from backend.server.base_manager import BaseManager, HealthInfo


class MemoryManager(BaseManager):
    async def start(self) -> None:
        store = MemoryStore()
        await store.start()
        app_state.memory = store

    async def stop(self) -> None:
        if app_state.memory is not None:
            await app_state.memory.stop()
            app_state.memory = None

    async def health(self) -> HealthInfo:
        if app_state.memory is None:
            return HealthInfo(status="down", detail="memory 未初始化")
        return HealthInfo(status="running")
