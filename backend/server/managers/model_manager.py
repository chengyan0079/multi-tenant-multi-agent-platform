"""模型工厂（LLM / bge-m3 / bge-reranker / bert-chinese）。"""
from __future__ import annotations

from backend.app_state import app_state
from backend.core.llm_factory import LLMFactory
from backend.server.base_manager import BaseManager


class ModelManager(BaseManager):
    async def start(self) -> None:
        factory = LLMFactory()
        await factory.start()
        app_state.llm_factory = factory

    async def stop(self) -> None:
        if app_state.llm_factory is not None:
            await app_state.llm_factory.stop()
            app_state.llm_factory = None
