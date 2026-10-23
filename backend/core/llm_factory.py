"""
llm_factory - 四模型统一封装（设计文档 §4）

LLM（生成+复杂路由）/ bge-m3（嵌入）/ bge-reranker-v2-m3（重排）/ bert-chinese（中文意图分类）。
三层兜底 + 重试：模型层异常时按配置回退；LLM 路由无本地模型兜底（DeepSeek 直接分类）。
"""
from __future__ import annotations

import asyncio
from typing import List, Optional

from langchain_core.language_models import BaseChatModel

from backend.app_state import app_state
from backend.common.logger import get_logger
from backend.core.exception import ModelError

logger = get_logger("llm_factory")


class LLMFactory:
    """模型工厂单例：集中构造与持有 LLM / Embedding / Reranker / Classifier。"""

    def __init__(self) -> None:
        self._llm: Optional[BaseChatModel] = None
        self._embedder = None
        self._reranker = None
        self._classifier = None

    async def start(self) -> None:
        """预加载模型客户端；缺失 key 时降级为 None 并在调用处再报错，不阻断启动。"""
        cfg = app_state.settings.model
        try:
            from langchain_openai import ChatOpenAI

            self._llm = ChatOpenAI(
                model=cfg.llm_model,
                api_key=cfg.api_key or "EMPTY",
                base_url=cfg.api_base,
                temperature=cfg.temperature,
                timeout=cfg.timeout_s,
                max_retries=cfg.max_retries,
            )
            logger.info(f"LLM 客户端就绪: {cfg.llm_model}")
        except Exception as exc:
            logger.warning(f"LLM 客户端初始化跳过: {exc}")
            self._llm = None

    @property
    def llm(self) -> BaseChatModel:
        if self._llm is None:
            raise ModelError("LLM 未初始化（检查 LLM_API_KEY/API_BASE）")
        return self._llm

    async def embed(self, texts: List[str]) -> dict:
        """bge-m3 向量化，返回 {'dense': [...], 'sparse': [...]}（与 RAG-Ultra ModelService 对齐）。

        dense 为归一化前的原始向量（记忆存储写入/查询时会统一 L2 归一化，使 IP==余弦）。
        sparse 为稀疏矩阵，记忆存储负责转成 {token_id: 权重}。
        """
        if self._embedder is None:
            await self._lazy_load_embedder()
        if self._embedder is None:
            raise ModelError("Embedding 未初始化（检查 bge-m3 依赖）")
        return await asyncio.to_thread(self._embedder.encode, texts)

    async def _lazy_load_embedder(self) -> None:
        try:
            from milvus_model.hybrid import BGEM3EmbeddingFunction

            self._embedder = BGEM3EmbeddingFunction(model_name=app_state.settings.model.embedding_model)
        except Exception as exc:
            logger.warning(f"Embedding 加载跳过: {exc}")

    async def rerank(self, query: str, documents: List[str], top_n: int = 5) -> List[float]:
        """bge-reranker-v2-m3 精排，返回与 documents 对齐的相关性分数。"""
        if self._reranker is None:
            try:
                from milvus_model.reranker import BGERerankFunction

                self._reranker = BGERerankFunction(model_name=app_state.settings.model.reranker_model)
            except Exception as exc:
                raise ModelError(f"Reranker 未初始化: {exc}")
        result = await asyncio.to_thread(self._reranker, query=query, documents=documents, top_n=top_n)
        return [float(s) for s in result.scores]

    async def classify(self, text: str) -> str:
        """bert-chinese 中文意图/文本分类快路径。未加载时降级为 'general'。"""
        if self._classifier is None:
            return "general"
        return await asyncio.to_thread(self._classifier.predict, text)

    async def stop(self) -> None:
        self._llm = self._embedder = self._reranker = self._classifier = None
