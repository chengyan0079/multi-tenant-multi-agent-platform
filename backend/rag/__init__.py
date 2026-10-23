"""rag 包：rag-ultra 集成适配层（不重建，仅适配）。"""
from backend.rag.adapter import Chunk, rag_retrieve

__all__ = ["Chunk", "rag_retrieve"]
