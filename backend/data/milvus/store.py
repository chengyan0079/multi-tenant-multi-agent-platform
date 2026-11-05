"""
milvus_store - 文档 RAG 向量存储（解析 MinIO 文件 → 切分 → BGE-M3 稠密+稀疏 → 写 Milvus）。

集合字段：chunk_id(主键) / tenant_id(分区键) / file_id / file_name / chunk_index / page /
content(文本) / dense(1024 维, 内积 IP + L2 归一化 == 余弦) / sparse(倒排, 内积)。
enable_dynamic_field=True，可挂任意额外元数据（如 heading / doc_type）。

参照 RAG-Ultra 的 MilvusStore 范式：
- dense 用 HNSW + IP，写入/查询两侧都做 L2 归一化，使内积(IP)等价于余弦；
- sparse 用 SPARSE_INVERTED_INDEX + IP（drop_ratio_build 丢弃最低权重 token 省存储）；
- 检索按 tenant_id（必选）+ file_id（可选）过滤，再做 dense / sparse 两路召回并融合（RRF / 加权）。

向量化复用已预热的 LLMFactory（bge-m3），全部 IO 异步。长记忆已不再走 Milvus，改落 PG。
"""
from __future__ import annotations

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


class DocumentMilvusStore:
    """文档 RAG 双向量存储（异步）。"""

    def __init__(self, client: AsyncMilvusClient | None = None) -> None:
        self.client = client

    @property
    def _name(self) -> str:
        return app_state.settings.milvus.collection

    def build_schema(self) -> CollectionSchema:
        """构建 RAG 文档集合的 CollectionSchema（chunk_id 主键 / tenant_id 分区键 / 双向量）。

        维度取配置 milvus.dense_dim（默认 1024，与 bge-m3 对齐）；enable_dynamic_field=True
        允许挂任意额外元数据（heading / doc_type 等）。
        """
        dim = app_state.settings.milvus.dense_dim
        return CollectionSchema(
            fields=[
                FieldSchema(name="chunk_id", dtype=DataType.VARCHAR, is_primary=True, max_length=64),
                FieldSchema(name="tenant_id", dtype=DataType.VARCHAR, max_length=64, is_partition_key=True),
                FieldSchema(name="file_id", dtype=DataType.VARCHAR, max_length=64),
                FieldSchema(name="file_name", dtype=DataType.VARCHAR, max_length=256),
                FieldSchema(name="chunk_index", dtype=DataType.INT32),
                FieldSchema(name="page", dtype=DataType.INT32),
                FieldSchema(name="content", dtype=DataType.VARCHAR, max_length=65535),
                FieldSchema(name="dense", dtype=DataType.FLOAT_VECTOR, dim=dim),
                FieldSchema(name="sparse", dtype=DataType.SPARSE_FLOAT_VECTOR),
            ],
            enable_dynamic_field=True,
        )

    def build_index_params(self) -> Any:
        """构建索引参数：dense/sparse 双向量 + file_id 标量倒排（租户内按文档收敛用）。

        - dense：HNSW + IP，配合写入/查询两侧 L2 归一化等价于余弦；
        - sparse：SPARSE_INVERTED_INDEX + IP；
        - file_id：INVERTED 标量索引。tenant_id 已作为分区键走分区剪枝，无需再建标量索引。
        """
        if self.client is None:
            raise RuntimeError("MilvusClient 未绑定，无法构建索引参数")
        index_params = self.client.prepare_index_params()
        index_params.add_index(
            field_name="dense", index_name="dense_index",
            index_type="HNSW", metric_type="IP",  # IP + 写入/查询两侧 L2 归一化 == 余弦
            params={"M": 16, "efConstruction": 128},
        )
        index_params.add_index(
            field_name="sparse", index_name="sparse_index",
            index_type="SPARSE_INVERTED_INDEX", metric_type="IP",
            params={"drop_ratio_build": 0.2},
        )
        index_params.add_index(
            field_name="file_id", index_name="file_id_index",
            index_type="INVERTED",
        )
        return index_params

    async def ensure_collection(self) -> None:
        """确保 RAG 文档集合就绪：缺失则建集合+索引并加载，已存在直接加载（启动时幂等调用）。

        本 store 持有的是 client.raw（AsyncMilvusClient 实例），它没有 ensure_collection；
        这里直接用原语实现幂等：has_collection 判断、create_collection 建集合+索引、
        load_collection 加载到内存。schema 与索引参数由本类的 build_schema / build_index_params 提供。
        """
        if self.client is None:
            raise RuntimeError("MilvusClient 未绑定")
        name = self._name
        if await self.client.has_collection(name):
            # 已存在：确保加载到内存即可（load_collection 对已加载集合是幂等的）
            await self.client.load_collection(name)
            logger.info(f"RAG 文档集合 [{name}] 已存在，已加载到内存")
            return
        schema = self.build_schema()
        index_params = self.build_index_params()
        await self.client.create_collection(name, schema=schema, index_params=index_params)
        await self.client.load_collection(name)
        logger.info(f"RAG 文档集合 [{name}] 已新建并加载到内存")

    async def add_chunks(self, chunks: list[dict[str, Any]], batch_size: int = 32) -> int:
        """批量写入文档切片向量。chunks 元素需含：
        text(必填) / tenant_id(必填) / file_id / file_name / chunk_index / page / 其它动态字段。
        返回写入条数。
        """
        if not chunks:
            return 0
        if self.client is None:
            raise RuntimeError("MilvusClient 未绑定")
        emb = await app_state.llm_factory.embed([c["text"] for c in chunks])
        total = 0
        reserved = (
            "chunk_id", "tenant_id", "file_id", "file_name",
            "chunk_index", "page", "text", "dense", "sparse",
        )
        for i in range(0, len(chunks), batch_size):
            batch = chunks[i:i + batch_size]
            data = []
            for idx, c in enumerate(batch):
                data.append({
                    "chunk_id": c.get("chunk_id") or f"{c['file_id']}:{c['chunk_index']}",
                    "tenant_id": str(c["tenant_id"]),
                    "file_id": str(c.get("file_id", "")),
                    "file_name": c.get("file_name", ""),
                    "chunk_index": int(c.get("chunk_index", 0)),
                    "page": int(c.get("page", 0)),
                    "content": c["text"],
                    "dense": _l2_normalize(emb["dense"][idx]),
                    "sparse": _parse_sparse_row(emb["sparse"], idx),
                    **{k: v for k, v in c.items() if k not in reserved},
                })
            await self.client.upsert(collection_name=self._name, data=data)
            total += len(data)
            logger.debug(f"批次 [{i // batch_size + 1}] 写入 {len(data)} 条文档向量")
        logger.info(f"文档向量写入完成，共 {total} 条")
        return total

    async def hybrid_search(
        self,
        *,
        query: str,
        tenant_id: str | int,
        file_id: str | None = None,
        top_k: int = 10,
        fusion: str = "rrf",
    ) -> list[dict[str, Any]]:
        """两路召回 + 融合。tenant_id 必选做隔离；file_id 可选进一步收敛到单文档。"""
        if not query or not query.strip():
            return []
        if self.client is None:
            raise RuntimeError("MilvusClient 未绑定")
        emb = await app_state.llm_factory.embed([query])
        dense_vec = _l2_normalize(emb["dense"][0])
        sparse_vec = _parse_sparse_row(emb["sparse"], 0)

        expr = f'tenant_id == "{tenant_id}"'
        if file_id:
            expr += f' and file_id == "{file_id}"'

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
            output_fields=["chunk_id", "tenant_id", "file_id", "file_name", "chunk_index", "page", "content"],
        )
        if not results or not results[0]:
            return []
        return [hit["entity"] for hit in results[0]]
