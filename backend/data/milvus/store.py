"""
milvus_store - 长期/语义记忆向量存储（设计文档 §6.1，参照 RAG-Ultra store.milvus_store）

集合字段：id(主键) / tenant_id(分区键) / agent_id / block / content / dense / sparse / created_at，
user_id 走动态字段（不重建集合也能加，检索时按它过滤）。
dense 用 bge-m3 的 1024 维，度量 IP；写入与查询两侧都做 L2 归一化，使内积(IP)等价于余弦
（与 RAG-Ultra 对齐）。sparse 用倒排索引 + IP。检索时按 tenant_id（必选）+ user_id + agent_id/block
过滤，再做 dense、sparse 两路召回并融合（RRF / 加权）。
使用 pymilvus 的 AsyncMilvusClient，全部 IO 异步，向量化经 LLMFactory.embed 在 to_thread 中执行。
"""
from __future__ import annotations

import asyncio
from typing import Any

import numpy as np

from pymilvus import (
    AnnSearchRequest,
    AsyncMilvusClient,
    DataType,
    FieldSchema,
    CollectionSchema,
    RRFRanker,
    WeightedRanker,
)

from backend.app_state import app_state
from backend.common.logger import logger


def _parse_sparse_row(sparse_matrix: Any, index: int) -> dict[int, float]:
    """把 BGEM3 返回的稀疏矩阵某一行转成 {token_id: 权重}。"""
    row = sparse_matrix[index]
    if hasattr(row, "tocoo"):
        coo = row.tocoo()
        return {int(col): float(val) for col, val in zip(coo.col, coo.data)}
    elif hasattr(row, "col") and hasattr(row, "data"):
        return {int(col): float(val) for col, val in zip(row.col, row.data)}
    return {}


def _l2_normalize(vec: Any) -> list[float]:
    """L2 归一化稠密向量：使内积(IP)等价于余弦。写入与查询两侧都调用，保证一致。"""
    arr = np.asarray(vec, dtype="float32")
    norm = float(np.linalg.norm(arr))
    return arr.tolist() if norm == 0.0 else (arr / norm).tolist()


class MemoryMilvusStore:
    """长期/语义记忆双向量存储（异步）。"""

    def __init__(self, client: AsyncMilvusClient | None = None) -> None:
        self.client = client

    @property
    def _name(self) -> str:
        return app_state.settings.milvus.collection

    async def ensure_collection(self) -> None:
        """确保集合就绪：不存在则创建集合与索引，已存在则直接加载（启动时调用，幂等）。"""
        name = self._name
        if self.client is None:
            raise RuntimeError("MilvusClient 未绑定")
        if not await self.client.has_collection(name):
            dim = app_state.settings.milvus.dense_dim
            schema = CollectionSchema(
                fields=[
                    FieldSchema(name="id", dtype=DataType.VARCHAR, is_primary=True, max_length=64),
                    FieldSchema(name="tenant_id", dtype=DataType.VARCHAR, max_length=64, is_partition_key=True),
                    FieldSchema(name="agent_id", dtype=DataType.VARCHAR, max_length=64),
                    FieldSchema(name="block", dtype=DataType.VARCHAR, max_length=32),
                    FieldSchema(name="content", dtype=DataType.VARCHAR, max_length=65535),
                    FieldSchema(name="dense", dtype=DataType.FLOAT_VECTOR, dim=dim),
                    FieldSchema(name="sparse", dtype=DataType.SPARSE_FLOAT_VECTOR),
                    FieldSchema(name="created_at", dtype=DataType.VARCHAR, max_length=32),
                ],
                enable_dynamic_field=True,
            )
            index_params = self.client.prepare_index_params()
            index_params.add_index(
                field_name="dense", index_name="dense_index",
                index_type="HNSW", metric_type="IP",
                params={"M": 16, "efConstruction": 128},
            )
            index_params.add_index(
                field_name="sparse", index_name="sparse_index",
                index_type="SPARSE_INVERTED_INDEX", metric_type="IP",
                params={"drop_ratio_build": 0.2},
            )
            await self.client.create_collection(name, schema=schema, index_params=index_params)
            logger.info(f"创建记忆集合 [{name}] 并建立索引")
        else:
            logger.info(f"记忆集合 [{name}] 已存在")
        await self.client.load_collection(name)
        logger.info(f"记忆集合 [{name}] 已加载到内存")

    async def add_memory(
        self,
        *,
        id: str,
        tenant_id: str,
        user_id: str,
        agent_id: str,
        block: str,
        content: str,
        created_at: str,
    ) -> None:
        """写入一条长期记忆：向量化 content 后 upsert（dense 归一化 + sparse）。

        user_id 写入动态字段，检索侧按同一 user_id 过滤，保证记忆不跨用户串。
        """
        if self.client is None:
            raise RuntimeError("MilvusClient 未绑定")
        emb = await app_state.llm_factory.embed([content])
        data = [{
            "id": id,
            "tenant_id": tenant_id,
            "user_id": user_id,
            "agent_id": agent_id,
            "block": block,
            "content": content,
            "dense": _l2_normalize(emb["dense"][0]),
            "sparse": _parse_sparse_row(emb["sparse"], 0),
            "created_at": created_at,
        }]
        await self.client.upsert(collection_name=self._name, data=data)
        logger.debug(f"写入长期记忆 id={id} block={block}")

    async def search(
        self,
        *,
        query: str,
        tenant_id: str,
        user_id: str,
        agent_id: str | None = None,
        block: str | None = None,
        top_k: int = 10,
        fusion: str = "rrf",
    ) -> list[dict[str, Any]]:
        """两路召回 + 融合。tenant_id + user_id 必选做隔离；可选 agent_id/block 进一步过滤。"""
        if not query or not query.strip():
            return []
        if self.client is None:
            raise RuntimeError("MilvusClient 未绑定")
        emb = await app_state.llm_factory.embed([query])
        dense_vec = _l2_normalize(emb["dense"][0])
        sparse_vec = _parse_sparse_row(emb["sparse"], 0)

        expr = f'tenant_id == "{tenant_id}" and user_id == "{user_id}"'
        if agent_id:
            expr += f' and agent_id == "{agent_id}"'
        if block:
            expr += f' and block == "{block}"'

        cfg = app_state.settings.milvus
        dense_req = AnnSearchRequest(
            data=[dense_vec], anns_field="dense",
            param={"metric_type": "IP", "params": {"ef": 64}},
            limit=top_k, expr=expr,
        )
        sparse_req = AnnSearchRequest(
            data=[sparse_vec], anns_field="sparse",
            param={"metric_type": "IP", "params": {"drop_ratio_search": 0.2}},
            limit=top_k, expr=expr,
        )
        ranker = (
            WeightedRanker(cfg.dense_weight, cfg.sparse_weight)
            if fusion == "weighted" else RRFRanker(k=cfg.rrf_k)
        )
        results = await self.client.hybrid_search(
            collection_name=self._name,
            reqs=[dense_req, sparse_req],
            ranker=ranker,
            limit=top_k,
            output_fields=["id", "tenant_id", "agent_id", "block", "content", "created_at"],
        )
        if not results or not results[0]:
            return []
        return [hit["entity"] for hit in results[0]]
