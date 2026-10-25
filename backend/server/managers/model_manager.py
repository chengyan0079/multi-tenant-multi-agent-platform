"""模型工厂（LLM / bge-m3 / bge-reranker / bert-chinese）。"""
from __future__ import annotations

from backend.app_state import app_state
from backend.common.llm.llm_factory import LLMFactory
from backend.server.base_manager import BaseManager, HealthInfo


class ModelManager(BaseManager):
    async def start(self) -> None:
        factory = LLMFactory()
        await factory.start()
        app_state.llm_factory = factory

    async def stop(self) -> None:
        if app_state.llm_factory is not None:
            await app_state.llm_factory.stop()
            app_state.llm_factory = None

    async def health(self) -> HealthInfo:
        if app_state.llm_factory is None:
            return HealthInfo(status="down", detail="llm_factory 未初始化")
        return HealthInfo(status="running")
