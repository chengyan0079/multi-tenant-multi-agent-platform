"""RAG 数据结构：加载页/分块/召回结果，字段对齐 qa/state.RankedChunk。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class LoadedPage:
    """文档加载后的单页/单篇文本。"""

    content: str  # 页/篇文本
    metadata: dict = field(default_factory=dict)  # 元信息（doc_type / 页码等）


@dataclass
class TextChunk:
    """分块后的文本单元（尚未向量化）。"""

    text: str  # 分块文本
    metadata: dict = field(default_factory=dict)  # 元信息（父片 / 序号等）


@dataclass
class Chunk:
    """检索命中的知识块（粗排或精排后的统一结构）。

    content 是命中的子片原文（精排输入）；parent_content 是所属父片全文；
    highlighted_content 是"父片里把命中子片用 <mark> 高亮标出"的文本，
    供 RAG 生成节点作为上下文使用（见 backend/agents/qa/prompts.py）。
    """

    content: str  # 命中子片原文（精排输入）
    score: float = 0.0  # 相关性分数
    source: str = ""  # 来源标识（文件 / 网页等）
    doc_id: str = ""  # 文档 id
    chunk_id: str = ""  # 块 id
    metadata: dict = field(default_factory=dict)  # 元信息
    parent_id: str = ""  # 所属父片 id
    parent_content: str = ""  # 父片全文
    highlighted_content: str = ""  # 父片内高亮命中子片的文本
    chunk_type: str = "child"  # child | parent
    extra: dict = field(default_factory=dict)  # 扩展字段
