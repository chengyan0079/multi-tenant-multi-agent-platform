"""rag 包：RAG 检索适配层（自研，参考 rag-ultra）。"""
from backend.mcp.retrieval.adapter import Chunk, rag_retrieve

__all__ = ["Chunk", "rag_retrieve"]
