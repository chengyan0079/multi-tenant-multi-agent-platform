"""
llm_factory - 四模型统一封装（设计文档 §4）

LLM（生成+复杂路由）/ bge-m3（嵌入）/ bge-reranker-v2-m3（重排）/ bert-chinese（中文意图分类）。
模型配置来自 model_registry 表（运行时由各 model_type 的 active 记录驱动），不再读 .env。
三层兜底 + 重试：模型层异常时降级；LLM 路由无本地模型兜底（DeepSeek 直接分类）。
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, List, Optional

from langchain_core.language_models import BaseChatModel

from backend.common.logger import get_logger
from backend.data.dao.agent.model_dao import ModelDao
from backend.observability.exception import ModelError

logger = get_logger("llm_factory")


class LLMFactory:
    """模型工厂单例：集中构造与持有 LLM / Embedding / Reranker / Classifier。"""

    def __init__(self) -> None:
        self._llm: Optional[BaseChatModel] = None
        self._embedder = None
        self._reranker = None
        self._classifier = None
        # 各 model_type 的 active 配置（start() 时从 model_registry 读取并缓存）
        self._cfg: dict[str, dict[str, Any]] = {}

    async def start(self) -> None:
        """预加载模型客户端；先做就绪自检，缺失 enabled 记录则启动阻断。"""
        await self._load_configs()
        await self._check_ready()
        llm = self._cfg.get("llm")
        if not llm:
            logger.warning("未配置 active LLM（model_registry 无 enabled 的 llm 记录）")
            self._llm = None
            return
        try:
            from langchain_openai import ChatOpenAI

            self._llm = ChatOpenAI(
                model=llm["name"],
                api_key=llm["api_key"] or "EMPTY",
                base_url=llm["base_url"],
                temperature=llm["temperature"] if llm["temperature"] is not None else 0.2,
                timeout=llm["timeout_s"] if llm["timeout_s"] is not None else 60,
                max_retries=llm["max_retries"] if llm["max_retries"] is not None else 2,
            )
            logger.info(f"LLM 客户端就绪: {llm['name']}")
        except Exception as exc:
            logger.warning(f"LLM 客户端初始化跳过: {exc}")
            self._llm = None

    async def _check_ready(self) -> None:
        """启动期就绪自检：llm/embedding/reranker/classifier 四类在 model_registry 中
        必须各至少有一条 enabled=true 记录，否则启动阻断（明确报错而非运行时才失败）。"""
        missing = []
        for mt in ("llm", "embedding", "reranker", "classifier"):
            try:
                n = await ModelDao.count_enabled(mt)
            except Exception as exc:
                raise RuntimeError(
                    f"模型就绪自检失败：无法查询 model_registry 的 {mt} 记录（DB 是否就绪？）: {exc}"
                ) from exc
            if n == 0:
                missing.append(mt)
        if missing:
            raise RuntimeError(
                "模型就绪自检未通过：以下类型在 model_registry 中无 enabled=true 记录，"
                f"启动阻断：{', '.join(missing)}"
            )
        logger.info("模型就绪自检通过：llm/embedding/reranker/classifier 均存在 enabled 记录")

    async def _load_configs(self) -> None:
        """从 model_registry 读取四类模型的 active 配置（enabled 且 sort_order 最小）。"""
        try:
            for mt in ("llm", "embedding", "reranker", "classifier"):
                self._cfg[mt] = await ModelDao.get_active(mt) or {}
        except Exception as exc:
            logger.warning(f"模型配置读取失败，将按未配置降级: {exc}")
            self._cfg = {k: {} for k in ("llm", "embedding", "reranker", "classifier")}

    @property
    def llm(self) -> BaseChatModel:
        if self._llm is None:
            raise ModelError("LLM 未初始化（检查 model_registry 的 llm 配置 / API_KEY/API_BASE）")
        return self._llm

    async def embed(self, texts: List[str]) -> dict:
        """bge-m3 向量化，返回 {'dense': [...], 'sparse': [...]}（与 RAG-Ultra ModelService 对齐）。

        dense 为归一化前的原始向量（记忆存储写入/查询时会统一 L2 归一化，使 IP==余弦）。
        sparse 为稀疏矩阵，记忆存储负责转成 {token_id: 权重}。
        """
        if self._embedder is None:
            await self._lazy_load_embedder()
        if self._embedder is None:
            raise ModelError("Embedding 未初始化（检查 model_registry 的 embedding 配置）")
        return await asyncio.to_thread(self._embedder.encode, texts)

    async def _lazy_load_embedder(self) -> None:
        cfg = self._cfg.get("embedding") or {}
        if not cfg:
            logger.warning("Embedding 未配置（model_registry 无 enabled 的 embedding 记录）")
            self._embedder = None
            return
        try:
            from milvus_model.hybrid import BGEM3EmbeddingFunction

            self._embedder = BGEM3EmbeddingFunction(model_name=cfg["name"])
        except Exception as exc:
            logger.warning(f"Embedding 加载跳过: {exc}")

    async def rerank(self, query: str, documents: List[str], top_n: int = 5) -> List[float]:
        """bge-reranker-v2-m3 精排，返回与 documents 对齐的相关性分数。"""
        if self._reranker is None:
            cfg = self._cfg.get("reranker") or {}
            if not cfg:
                raise ModelError("Reranker 未配置（model_registry 无 enabled 的 reranker 记录）")
            try:
                from milvus_model.reranker import BGERerankFunction

                self._reranker = BGERerankFunction(model_name=cfg["name"])
            except Exception as exc:
                raise ModelError(f"Reranker 未初始化: {exc}")
        result = await asyncio.to_thread(self._reranker, query=query, documents=documents, top_n=top_n)
        return [float(s) for s in result.scores]

    async def classify(self, text: str) -> str:
        """bert-chinese 中文意图分类（消费离线训练产物）。

        仅当 model_registry 的 classifier 记录配置了 endpoint_path 时加载；
        未配置或加载失败降级为 'general'。
        产物由 offline/ 模块训练产出（HF 格式 + meta.json：labels 顺序 + max_len）。
        """
        if self._classifier is None:
            await self._lazy_load_classifier()
        if self._classifier is None:
            return "general"
        model, tokenizer, labels, max_len = self._classifier
        return await asyncio.to_thread(self._classify_one, model, tokenizer, labels, max_len, text)

    @staticmethod
    def _classify_one(model, tokenizer, labels: list, max_len: int, text: str) -> str:
        import torch

        enc = tokenizer(
            text, return_tensors="pt", truncation=True, padding="max_length", max_length=max_len
        )
        with torch.no_grad():
            logits = model(**enc).logits
        idx = int(logits.argmax(dim=-1).item())
        return labels[idx] if 0 <= idx < len(labels) else "general"

    async def _lazy_load_classifier(self) -> None:
        """按 model_registry 的 classifier.endpoint_path 懒加载离线意图分类产物（只读消费）。"""
        cfg = self._cfg.get("classifier") or {}
        endpoint_path = cfg.get("endpoint_path")
        if not endpoint_path:
            self._classifier = None
            return
        try:
            import json as _json

            from transformers import AutoModelForSequenceClassification, AutoTokenizer

            d = Path(endpoint_path)
            meta = _json.loads((d / "meta.json").read_text(encoding="utf-8"))
            tokenizer = AutoTokenizer.from_pretrained(d)
            model = AutoModelForSequenceClassification.from_pretrained(d)
            model.eval()
            self._classifier = (model, tokenizer, meta["labels"], int(meta.get("max_len", 64)))
            logger.info(f"意图分类器就绪: {d}")
        except Exception as exc:
            logger.warning(f"意图分类器加载跳过（将以 general 兜底）: {exc}")
            self._classifier = None

    async def stop(self) -> None:
        self._llm = self._embedder = self._reranker = self._classifier = None
        self._cfg = {}
