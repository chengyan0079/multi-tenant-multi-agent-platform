"""
adapter - rag-ultra 适配层对外暴露的检索工具（设计文档 §6.2）

qa Agent 的 retrieve 节点直接消费 rag_retrieve(query, tenant_id, top_k)。
tenant_id 透传为 Milvus partition key，保证知识不跨租户外泄。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from backend.rag.client import client


@dataclass
class Chunk:
    """检索命中的知识块。"""

    content: str
    score: float
    source: str = ""
    metadata: dict = field(default_factory=dict)


async def rag_retrieve(query: str, tenant_id: str, top_k: int = 5) -> List[Chunk]:
    """对外检索工具：经 rag-ultra 客户端取回并封装为 Chunk。"""
    raw = await client.retrieve(query, tenant_id, top_k)
    return [
        Chunk(
            content=item.get("content", ""),
            score=float(item.get("score", 0.0)),
            source=item.get("source", ""),
            metadata=item.get("metadata", {}),
        )
        for item in raw
    ]
