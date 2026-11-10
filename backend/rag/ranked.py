"""RAG 数据结构：加载页/分块/召回结果，字段对齐 qa/state.RankedChunk。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class LoadedPage:
    """文档加载后的单页/单篇文本。"""

    content: str
    metadata: dict = field(default_factory=dict)


@dataclass
class TextChunk:
    """分块后的文本单元（尚未向量化）。"""

    text: str
    metadata: dict = field(default_factory=dict)


@dataclass
class Chunk:
    """检索命中的知识块（粗排或精排后的统一结构）。

    content 是命中的子片原文（精排输入）；parent_content 是所属父片全文；
    highlighted_content 是"父片里把命中子片用 <mark> 高亮标出"的文本，
    供 RAG 生成节点作为上下文使用（见 backend/agents/qa/prompts.py）。
    """

    content: str
    score: float = 0.0
    source: str = ""
    doc_id: str = ""
    chunk_id: str = ""
    metadata: dict = field(default_factory=dict)
    parent_id: str = ""
    parent_content: str = ""
    highlighted_content: str = ""
    chunk_type: str = "child"
    extra: dict = field(default_factory=dict)
