"""
milvus_store - 文档 RAG 向量存储（解析 MinIO 文件 → 切分 → BGE-M3 稠密+稀疏 → 写 Milvus）。

集合字段：chunk_id(主键) / tenant_id(分区键) / file_id / file_name / parent_id / parent_content /
chunk_type / chunk_index / page / source_location / content(子片文本) / extra(JSON 额外字段) /
dense(1024 维, 内积 IP + L2 归一化 == 余弦) / sparse(倒排, 内积)。

父子片（small-to-big，参照 RAG-Ultra）：集合只存**子片**（子片才有向量做精准召回），
每个子片冗余存父片全文 parent_content；命中子片后由 retrieval 把父片里对应子片高亮，
交给 LLM 时既保留上下文又标明命中重点。

所有需要返回/过滤的字段都**显式声明**：Milvus 的 output_fields 不能可靠取回动态字段，
早期版本把 source_location/doc_type/file_hash 塞进动态字段导致检索时取不到值。

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


def _tenant_key(tenant_id: Any) -> str:
    """租户分区键：None（超管 / 平台级文件）统一记为 "0"。

    写入侧（indexing）已用 `tenant_id or 0`，检索侧必须同样规范化，
    否则会拼出 `tenant_id == "None"` 而永远召回不到平台级数据。
    """
    return str(tenant_id if tenant_id is not None else 0)


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

    # 检索输出字段（必须显式声明在 schema 中，动态字段无法可靠返回）
    OUTPUT_FIELDS: tuple[str, ...] = (
        "chunk_id", "tenant_id", "file_id", "file_name",
        "parent_id", "parent_content", "chunk_type", "chunk_index", "page",
        "source_location", "content", "extra",
    )
    # schema 版本校验用的必需字段：集合缺任一字段即视为旧 schema，需要重建
    REQUIRED_FIELDS: frozenset[str] = frozenset({
        "parent_id", "parent_content", "chunk_type", "source_location", "extra",
    })

    def build_schema(self) -> CollectionSchema:
        """构建 RAG 文档集合的 CollectionSchema（父子片 + 显式额外字段 + 双向量）。"""
        dim = app_state.settings.milvus.dense_dim
        return CollectionSchema(
            fields=[
                FieldSchema(
                    name="chunk_id", dtype=DataType.VARCHAR,
                    is_primary=True, max_length=128,
                ),
                FieldSchema(
                    name="tenant_id", dtype=DataType.VARCHAR,
                    max_length=64, is_partition_key=True,
                ),
                FieldSchema(name="file_id", dtype=DataType.VARCHAR, max_length=64),
                FieldSchema(name="file_name", dtype=DataType.VARCHAR, max_length=256),
                # —— 父子片（参照 RAG-Ultra：只存子片，冗余父片全文）——
                FieldSchema(name="parent_id", dtype=DataType.VARCHAR, max_length=128),
                FieldSchema(name="parent_content", dtype=DataType.VARCHAR, max_length=65535),
                FieldSchema(name="chunk_type", dtype=DataType.VARCHAR, max_length=32),
                FieldSchema(name="chunk_index", dtype=DataType.INT32),
                FieldSchema(name="page", dtype=DataType.INT32),
                FieldSchema(
                    name="source_location", dtype=DataType.VARCHAR, max_length=512,
                ),
                FieldSchema(name="content", dtype=DataType.VARCHAR, max_length=65535),
                # 额外字段统一收口（doc_type / file_hash / 标题路径 / 其它元数据）
                FieldSchema(name="extra", dtype=DataType.JSON),
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
        index_params.add_index(
            field_name="parent_id", index_name="parent_id_index",
            index_type="INVERTED",
        )
        return index_params

    async def _create_and_load(self) -> None:
        schema = self.build_schema()
        index_params = self.build_index_params()
        await self.client.create_collection(self._name, schema=schema, index_params=index_params)
        await self.client.load_collection(self._name)

    async def rebuild_collection(self) -> None:
        """删除并重建集合（schema 升级用；会清空已有向量，需重新 /parse 导入）。"""
        if self.client is None:
            raise RuntimeError("MilvusClient 未绑定")
        if await self.client.has_collection(self._name):
            await self.client.drop_collection(self._name)
        await self._create_and_load()
        logger.warning(f"RAG 文档集合 [{self._name}] 已重建（旧数据已清空，请重新导入文档）")

    async def ensure_collection(self) -> None:
        """确保 RAG 文档集合就绪（启动时幂等调用）。

        Milvus 不支持给已有集合加字段；这里用 describe_collection 校验必需字段，
        发现旧 schema 时 fail-fast 明确提示重建，避免"新字段写入失败/检索取不回"的静默故障。
        """
        if self.client is None:
            raise RuntimeError("MilvusClient 未绑定")
        name = self._name
        if await self.client.has_collection(name):
            info = await self.client.describe_collection(name)
            existing = {f["name"] for f in info.get("fields", [])}
            missing = self.REQUIRED_FIELDS - existing
            if missing:
                raise RuntimeError(
                    f"RAG 文档集合 [{name}] 是旧 schema，缺少字段 {sorted(missing)}；"
                    "请调用 DocumentMilvusStore.rebuild_collection() 重建后重新导入文档"
                )
            await self.client.load_collection(name)
            logger.info(f"RAG 文档集合 [{name}] 已存在，schema 校验通过，已加载到内存")
            return
        await self._create_and_load()
        logger.info(f"RAG 文档集合 [{name}] 已新建并加载到内存")

    async def add_chunks(self, chunks: list[dict[str, Any]], batch_size: int = 32) -> int:
        """批量写入子片向量（父子片：只写子片行）。chunks 元素需含：
        text(必填，子片正文) / tenant_id / file_id / parent_id / parent_content /
        chunk_type / chunk_index / page / source_location / extra(JSON 额外字段)。
        返回写入条数。

        每批独立向量化：避免一次性 embed 整个大文件占满内存，也避免批内索引
        与全局 embed 结果错位（多批次时曾导致第 2 批复用第 1 批的向量）。
        """
        if not chunks:
            return 0
        if self.client is None:
            raise RuntimeError("MilvusClient 未绑定")
        total = 0
        for i in range(0, len(chunks), batch_size):
            batch = chunks[i:i + batch_size]
            emb = await app_state.llm_factory.embed([c["text"] for c in batch])
            data = []
            for idx, c in enumerate(batch):
                parent_id = str(c.get("parent_id") or "")
                child_seq = int(c.get("child_index", c.get("chunk_index", idx)))
                data.append({
                    "chunk_id": c.get("chunk_id") or f"{parent_id}:child:{child_seq}",
                    "tenant_id": _tenant_key(c["tenant_id"]),
                    "file_id": str(c.get("file_id", "")),
                    "file_name": c.get("file_name", ""),
                    "parent_id": parent_id,
                    "parent_content": c.get("parent_content") or c["text"],
                    "chunk_type": c.get("chunk_type") or "child",
                    "chunk_index": int(c.get("chunk_index", 0)),
                    "page": int(c.get("page", 0) or 0),
                    "source_location": c.get("source_location", ""),
                    "content": c["text"],
                    "extra": c.get("extra") or {},
                    "dense": _l2_normalize(emb["dense"][idx]),
                    "sparse": _parse_sparse_row(emb["sparse"], idx),
                })
            await self.client.upsert(collection_name=self._name, data=data)
            total += len(data)
            logger.debug(f"批次 [{i // batch_size + 1}] 写入 {len(data)} 条子片向量")
        logger.info(f"文档向量写入完成，共 {total} 条子片")
        return total

    async def delete_by_file_id(self, file_id: str | int) -> None:
        """删除某文件的全部向量块（重新解析前调用，保证幂等）。

        file_id 是 agent_file 主键，全局唯一；删除后再 upsert，避免分块数变少时旧块残留。
        """
        if self.client is None:
            raise RuntimeError("MilvusClient 未绑定")
        safe_id = str(file_id).replace("\\", "\\\\").replace('"', '\\"')
        await self.client.delete(
            collection_name=self._name,
            filter=f'file_id == "{safe_id}"',
        )

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
        emb = await app_state.llm_factory.embed([query], query=True)
        dense_vec = _l2_normalize(emb["dense"][0])
        sparse_vec = _parse_sparse_row(emb["sparse"], 0)

        # 过滤表达式的值必须转义，避免 file_id 等外部入参注入 Milvus expr
        def _safe(value: object) -> str:
            return str(value).replace("\\", "\\\\").replace('"', '\\"')

        expr = f'tenant_id == "{_safe(_tenant_key(tenant_id))}"'
        if file_id:
            expr += f' and file_id == "{_safe(file_id)}"'

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
            output_fields=list(self.OUTPUT_FIELDS),
        )
        if not results or not results[0]:
            return []
        # 保留 distance 作为粗排分数：精排不可用时可作为降级依据，也便于排查召回质量
        return [
            {**hit["entity"], "score": float(hit.get("distance") or 0.0)}
            for hit in results[0]
        ]
