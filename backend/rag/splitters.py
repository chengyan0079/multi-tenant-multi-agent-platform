"""文档分块：父子片两阶段切分 + 标题感知，子片带向量、父片回填上下文并高亮。"""

from __future__ import annotations

from langchain_text_splitters import (
    MarkdownHeaderTextSplitter,
    MarkdownTextSplitter,
    RecursiveCharacterTextSplitter,
)

from backend.common.logger import logger
from backend.config import config
from backend.rag.ranked import LoadedPage, TextChunk

_HEADERS_TO_SPLIT_ON = [
    ("#", "H1"),
    ("##", "H2"),
    ("###", "H3"),
    ("####", "H4"),
]

_SEPARATORS = [
    "\n\n",  # 强段落
    "\n",  # 换行
    r"。|！|？",  # 中文句末
    r"\.\s|\!\s|\?\s",  # 英文句末（带空格）
    r"；|;\s",  # 分号
    r"，|,\s",  # 逗号
    " ",  # 空格
    "",  # 字符级兜底
]

# 显式字段（store.add_chunks 会读取）；其余元数据收口进 extra
_RESERVED_META = frozenset(
    {
        "parent_id",
        "parent_content",
        "chunk_type",
        "chunk_index",
        "child_index",
        "page",
        "source_location",
        "file_name",
        "file_id",
        "tenant_id",
        "text",
        "extra",
    }
)


def _recursive_splitter(*, chunk_size: int, chunk_overlap: int) -> RecursiveCharacterTextSplitter:
    return RecursiveCharacterTextSplitter(
        separators=_SEPARATORS,
        keep_separator="end",
        is_separator_regex=True,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )


def _parent_chunks_plain(pages: list[LoadedPage]) -> list[tuple[str, dict]]:
    """PDF/TXT：按页用大块递归切分产生父片，保留页元数据。"""
    splitter = _recursive_splitter(
        chunk_size=config.qa.parent_chunk_size,
        chunk_overlap=config.qa.parent_chunk_overlap,
    )
    out: list[tuple[str, dict]] = []
    for page in pages:
        if len(page.content.strip()) < 16:
            continue
        meta = dict(page.metadata)
        for piece in splitter.split_text(page.content):
            if piece.strip():
                out.append((piece, meta))
    return out


def _parent_chunks_markdown(pages: list[LoadedPage]) -> list[tuple[str, dict]]:
    """Markdown：先按 H1~H4 标题分节，再对过长小节用大块切分，标题路径写入 source_location。"""
    header_splitter = MarkdownHeaderTextSplitter(
        headers_to_split_on=_HEADERS_TO_SPLIT_ON,
        return_each_line=False,
        strip_headers=False,
    )
    long_splitter = _recursive_splitter(
        chunk_size=config.qa.parent_chunk_size,
        chunk_overlap=config.qa.parent_chunk_overlap,
    )
    out: list[tuple[str, dict]] = []
    for page in pages:
        for header_chunk in header_splitter.split_text(page.content):
            meta = {**page.metadata, **header_chunk.metadata}
            titles = [str(meta[h]) for h in ("H1", "H2", "H3", "H4") if meta.get(h)]
            meta["source_location"] = " > ".join([meta["file_name"], *titles])
            pieces = (
                long_splitter.split_text(header_chunk.page_content)
                if len(header_chunk.page_content) > config.qa.parent_chunk_size
                else [header_chunk.page_content]
            )
            for piece in pieces:
                if piece.strip():
                    out.append((piece, meta))
    return out


def _child_split(parent_text: str) -> list[str]:
    child_splitter = _recursive_splitter(
        chunk_size=config.qa.child_chunk_size,
        chunk_overlap=config.qa.child_chunk_overlap,
    )
    return [p for p in child_splitter.split_text(parent_text) if p.strip()]


def split_documents(
    pages: list[LoadedPage], *, file_ext: str, file_id: str = ""
) -> list[TextChunk]:
    """统一分块入口：父片 → 子片，返回带父子关系与全局 chunk_index 的子片列表。

    parent_id 规则：{file_id}:parent:{父片序号}（file_id 由 indexing 传入，保证跨文件唯一）；
    chunk_id 由 store.add_chunks 按 {parent_id}:child:{子片序号} 生成。
    """
    ext = (file_ext or "").lower()
    if ext == ".md":
        parents = _parent_chunks_markdown(pages)
    elif ext in (".pdf", ".txt"):
        parents = _parent_chunks_plain(pages)
    else:
        raise ValueError(f"不支持的文件类型 [{ext}]")

    chunks: list[TextChunk] = []
    for parent_seq, (parent_text, parent_meta) in enumerate(parents):
        parent_id = f"{file_id}:parent:{parent_seq}"
        source_location = parent_meta.get("source_location", parent_meta.get("file_name", ""))
        extra = {k: v for k, v in parent_meta.items() if k not in _RESERVED_META}
        pieces = _child_split(parent_text)
        for child_seq, piece in enumerate(pieces):
            meta = {
                **parent_meta,
                "parent_id": parent_id,
                "parent_content": parent_text,
                "parent_index": parent_seq,
                "child_index": child_seq,
                "chunk_type": "child",
                "source_location": source_location,
                "extra": dict(extra),
                "char_count": len(piece),
            }
            chunks.append(TextChunk(text=piece, metadata=meta))

    for idx, chunk in enumerate(chunks):
        chunk.metadata["chunk_index"] = idx
    logger.debug(
        f"rag.split.done | pages={len(pages)} parents={len(parents)} "
        f"children={len(chunks)} ext={ext}"
    )
    return chunks
