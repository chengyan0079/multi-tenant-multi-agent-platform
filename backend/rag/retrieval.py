"""向量检索 + 精排：qa Agent 的唯一检索入口。

参照 thy-edu-agent/core/reranker.py 的 "混合召回 → BGE-Reranker 精排 → confidence"
流水线，按本项目改造：
- 粗排用 DocumentMilvusStore.hybrid_search（本项目 Milvus，tenant_id 分区键隔离）；
- 精排复用已预热的 LLMFactory.rerank，不另加载 torch 模型；
- 精排不可用时降级为粗排分数（不阻断生成链路）；
- 返回 backend.rag.ranked.Chunk，字段与 qa/state.py 的 RankedChunk 对齐。
"""
from __future__ import annotations

from backend.app_state import app_state
from backend.common.logger import logger
from backend.config import config
from backend.rag.ranked import Chunk

MARK_OPEN, MARK_CLOSE = "<mark>", "</mark>"


def _merge_spans(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """合并重叠/相邻的高亮区间，避免嵌套标记。"""
    if not spans:
        return []
    spans.sort()
    merged: list[list[int]] = [list(spans[0])]
    for start, end in spans[1:]:
        last = merged[-1]
        if start <= last[1]:
            last[1] = max(last[1], end)
        else:
            merged.append([start, end])
    return [(s, e) for s, e in merged]


def highlight_parent(parent_content: str, hit_children: list[str]) -> str:
    """在父片原文中把命中子片用 <mark> 高亮，其余保持为上下文。

    - 子片来自父片切分，通常能精确匹配；带 overlap 的多个子片会合并区间；
    - 匹配不到时降级为"父片全文 + 命中片段列表"，保证 LLM 仍能看到重点；
    - 父片为空时直接高亮子片本身。
    """
    children = [c.strip() for c in hit_children if c and c.strip()]
    if not children:
        return ""
    if not parent_content:
        return f"{MARK_OPEN}{children[0]}{MARK_CLOSE}"

    spans: list[tuple[int, int]] = []
    for child in children:
        start = 0
        while True:
            pos = parent_content.find(child, start)
            if pos < 0:
                break
            spans.append((pos, pos + len(child)))
            start = pos + 1
    merged = _merge_spans(spans)
    if not merged:
        listed = "\n".join(f"- {MARK_OPEN}{c}{MARK_CLOSE}" for c in children)
        return f"{parent_content}\n\n【命中片段】\n{listed}"

    out = parent_content
    for start, end in reversed(merged):
        out = out[:end] + MARK_CLOSE + out[end:]
        out = out[:start] + MARK_OPEN + out[start:]
    return out


def _apply_highlights(chunks: list[Chunk]) -> None:
    """按 parent_id 分组，把同父片的所有命中子片一起高亮到各自 highlighted_content。"""
    grouped: dict[str, list[str]] = {}
    for c in chunks:
        key = c.parent_id or c.chunk_id
        grouped.setdefault(key, []).append(c.content)
    for c in chunks:
        key = c.parent_id or c.chunk_id
        siblings = grouped.get(key, [c.content])
        c.highlighted_content = (
            highlight_parent(c.parent_content, siblings)
            if c.parent_content else ""
        )


def _to_chunk(entity: dict, score: float) -> Chunk:
    """Milvus entity → 统一检索结果。"""
    file_name = str(entity.get("file_name") or "")
    page = int(entity.get("page") or 0)
    source_location = str(entity.get("source_location") or "")
    if not source_location:
        source_location = f"{file_name} > 第 {page} 页" if page else file_name
    extra = entity.get("extra") or {}
    if not isinstance(extra, dict):
        extra = {}
    return Chunk(
        content=str(entity.get("content") or ""),
        score=float(score),
        source=source_location,
        doc_id=str(entity.get("file_id") or ""),
        chunk_id=str(entity.get("chunk_id") or ""),
        metadata={
            "file_name": file_name,
            "page": page,
            "chunk_index": entity.get("chunk_index"),
            "source_location": source_location,
        },
        parent_id=str(entity.get("parent_id") or ""),
        parent_content=str(entity.get("parent_content") or ""),
        chunk_type=str(entity.get("chunk_type") or "child"),
        extra=extra,
    )


async def _rerank(query: str, candidates: list[dict]) -> list[float] | None:
    """调用已预热的 bge-reranker；不可用时返回 None 由调用方降级。"""
    factory = app_state.llm_factory
    if factory is None or not candidates:
        return None
    docs = [
        str(c.get("content") or "")[: config.qa.rerank_max_input_chars]
        for c in candidates
    ]
    try:
        return await factory.rerank(query, docs, top_n=len(docs))
    except Exception as exc:  # noqa: BLE001 - 精排失败降级为粗排，不阻断生成链路
        logger.warning(f"rag.retrieve: 精排不可用，降级粗排 | {exc}")
        return None


async def retrieve(
    query: str,
    tenant_id: int,
    *,
    top_k: int | None = None,
    file_id: str | None = None,
) -> list[Chunk]:
    """混合召回 + 精排，返回按相关性降序的 Top-K 片段。

    top_k 为最终返回条数；粗排召回数取 max(top_k, config.qa.recall_top_k)，
    保证精排有足够候选。空结果返回 []（confidence 由调用方按首条分数判定）。
    """
    if not query or not query.strip():
        return []
    store = app_state.milvus_store
    if store is None or store.client is None:
        raise RuntimeError("Milvus 存储未就绪")

    final_k = top_k or config.qa.rerank_top_k
    recall_k = max(final_k, config.qa.recall_top_k)
    candidates = await store.hybrid_search(
        query=query, tenant_id=tenant_id, file_id=file_id, top_k=recall_k,
    )
    if not candidates:
        logger.debug(f"rag.retrieve: 召回为空 query={query[:50]!r} tenant={tenant_id}")
        return []

    scores = await _rerank(query, candidates)
    if scores is None:
        # 精排降级：用 Milvus 粗排 distance
        pairs = [(c, float(c.get("score") or 0.0)) for c in candidates]
        logger.debug("rag.retrieve: 使用粗排分数")
    else:
        pairs = [(c, float(s)) for c, s in zip(candidates, scores)]

    pairs.sort(key=lambda x: x[1], reverse=True)
    result = [_to_chunk(entity, score) for entity, score in pairs[:final_k]]
    _apply_highlights(result)
    logger.debug(
        f"rag.retrieve.done | query={query[:50]!r} candidates={len(candidates)} "
        f"returned={len(result)} top_score={result[0].score if result else 0.0:.4f}"
    )
    return result
