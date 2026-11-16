"""backend/rag 自研链路单测：bytes 加载、分块、精排降级、解析入库状态回写。

不连真实 MinIO / Milvus / 模型；用 fake 对象验证结构与调用顺序。
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.rag.loaders import load_document
from backend.rag.ranked import Chunk
from backend.rag.splitters import split_documents


def test_load_txt_bytes_and_metadata() -> None:
    pages = load_document("你好，这是一段中文文本。".encode("utf-8"), file_name="a.txt", file_ext=".txt")
    assert len(pages) == 1
    assert pages[0].content == "你好，这是一段中文文本。"
    assert pages[0].metadata["doc_type"] == "txt"
    assert pages[0].metadata["file_hash"]
    assert pages[0].metadata["source_location"] == "a.txt"


def test_load_markdown_strips_front_matter() -> None:
    raw = "---\ntitle: t\n---\n\n# 标题\n\n正文内容".encode("utf-8")
    pages = load_document(raw, file_name="a.md", file_ext=".md")
    assert len(pages) == 1
    assert "title" not in pages[0].content
    assert "正文内容" in pages[0].content


def test_load_unsupported_ext_raises() -> None:
    with pytest.raises(ValueError):
        load_document(b"x", file_name="a.docx", file_ext=".docx")


def test_split_txt_assigns_global_chunk_index_and_parent_relation() -> None:
    text = "".join(f"这是第{i}段关于知识库的说明文字，用于验证分块逻辑是否正常工作。\n\n" for i in range(40))
    pages = load_document(text.encode("utf-8"), file_name="a.txt", file_ext=".txt")
    chunks = split_documents(pages, file_ext=".txt", file_id="9")
    assert len(chunks) > 1
    assert [c.metadata["chunk_index"] for c in chunks] == list(range(len(chunks)))
    assert all(c.text.strip() for c in chunks)
    # 父子片：每个子片都带稳定 parent_id 与父片全文，且子片文本确实来自父片
    assert all(c.metadata["parent_id"].startswith("9:parent:") for c in chunks)
    assert all(c.metadata["parent_content"] for c in chunks)
    assert all(c.text.strip() in c.metadata["parent_content"] for c in chunks)
    assert {c.metadata["chunk_type"] for c in chunks} == {"child"}
    parent_ids = {c.metadata["parent_id"] for c in chunks}
    assert len(parent_ids) > 1
    assert all(any(c.metadata["parent_id"] == pid for c in chunks) for pid in parent_ids)


def test_split_markdown_keeps_title_in_source_location() -> None:
    raw = "# 一级\n\n## 二级\n\n" + "正文内容，用于验证标题路径。" * 20
    pages = load_document(raw.encode("utf-8"), file_name="a.md", file_ext=".md")
    chunks = split_documents(pages, file_ext=".md", file_id="9")
    assert chunks
    assert "一级" in chunks[0].metadata["source_location"]


def test_highlight_parent_marks_all_hit_children() -> None:
    from backend.rag.retrieval import MARK_CLOSE, MARK_OPEN, highlight_parent

    parent = "前言说明。核心结论是向量检索需要归一化。补充说明：索引参数另见配置。"
    child_a = "核心结论是向量检索需要归一化"
    child_b = "索引参数另见配置"
    out = highlight_parent(parent, [child_a, child_b])
    assert out.count(MARK_OPEN) == 2
    assert out.count(MARK_CLOSE) == 2
    assert f"{MARK_OPEN}{child_a}{MARK_CLOSE}" in out
    assert f"{MARK_OPEN}{child_b}{MARK_CLOSE}" in out
    # 未命中部分仍作为上下文保留
    assert "前言说明。" in out


def test_highlight_parent_merges_overlapping_children() -> None:
    from backend.rag.retrieval import MARK_CLOSE, MARK_OPEN, highlight_parent

    out = highlight_parent("甲乙丙丁戊", ["甲乙丙", "丙丁戊"])
    assert out.count(MARK_OPEN) == 1
    assert f"{MARK_OPEN}甲乙丙丁戊{MARK_CLOSE}" in out


def test_highlight_parent_falls_back_when_child_not_found() -> None:
    from backend.rag.retrieval import MARK_OPEN, highlight_parent

    out = highlight_parent("父片原文", ["外部片段"])
    assert "父片原文" in out
    assert "【命中片段】" in out
    assert out.count(MARK_OPEN) == 1


def test_highlight_parent_without_parent() -> None:
    from backend.rag.retrieval import MARK_CLOSE, MARK_OPEN, highlight_parent

    assert f"{MARK_OPEN}子片{MARK_CLOSE}" == highlight_parent("", ["子片"])


@pytest.mark.asyncio
async def test_retrieve_falls_back_to_coarse_scores(monkeypatch) -> None:
    from backend.rag import retrieval

    class FakeStore:
        client = object()

        async def hybrid_search(self, **kwargs):
            assert kwargs["tenant_id"] == 7
            return [
                {"content": "A", "file_name": "a.txt", "page": 1,
                 "file_id": "1", "chunk_id": "1:0", "parent_id": "1:parent:0",
                 "parent_content": "前言 A 后记", "extra": {}, "score": 0.9},
                {"content": "B", "file_name": "b.txt", "page": 2,
                 "file_id": "2", "chunk_id": "2:0", "parent_id": "2:parent:0",
                 "parent_content": "前言 B 后记", "extra": {"doc_type": "txt"}, "score": 0.4},
            ]

    app_state = SimpleNamespace(
        milvus_store=FakeStore(),
        llm_factory=None,  # 精排不可用 → 降级粗排
    )
    monkeypatch.setattr(retrieval, "app_state", app_state)

    result = await retrieval.retrieve("问题", 7, top_k=2)
    assert len(result) == 2
    assert [c.content for c in result] == ["A", "B"]
    assert result[0].score >= result[1].score
    assert isinstance(result[0], Chunk)
    assert result[0].source
    # 父片内高亮：命中子片被 <mark> 包住，父片其余部分保留
    assert "<mark>A</mark>" in result[0].highlighted_content
    assert "前言" in result[0].highlighted_content
    assert result[1].extra["doc_type"] == "txt"
    # 降级粗排：标记未使用精排（RRF 分数不可当相似度）
    assert result[1].extra["_rerank_used"] is False


@pytest.mark.asyncio
async def test_retrieve_uses_rerank_scores(monkeypatch) -> None:
    from backend.rag import retrieval

    class FakeStore:
        client = object()

        async def hybrid_search(self, **kwargs):
            return [
                {"content": "A", "file_name": "a.txt", "score": 0.1},
                {"content": "B", "file_name": "b.txt", "score": 0.9},
            ]

    class FakeFactory:
        async def rerank(self, query, documents, top_n):
            assert documents == ["A", "B"]
            return [0.95, 0.20]  # 精排把 B 排到后面

    monkeypatch.setattr(retrieval, "app_state", SimpleNamespace(
        milvus_store=FakeStore(), llm_factory=FakeFactory(),
    ))
    result = await retrieval.retrieve("问题", 1, top_k=2)
    assert [c.content for c in result] == ["A", "B"]
    assert result[0].score == 0.95


@pytest.mark.asyncio
async def test_index_document_writes_and_marks_parsed(monkeypatch) -> None:
    from backend.rag import indexing

    calls: list[tuple] = []

    class FakeStore:
        client = object()

        async def add_chunks(self, rows, batch_size=32):
            calls.append(("add", len(rows), batch_size))
            # 每个子片都必须带父片关系与显式字段
            assert all(r["parent_id"].startswith("9:parent:") for r in rows)
            assert all(r["parent_content"] and r["text"] in r["parent_content"] for r in rows)
            assert all(r["chunk_type"] == "child" and isinstance(r["extra"], dict) for r in rows)
            assert all(r["source_location"] for r in rows)
            return len(rows)

        async def delete_by_file_id(self, file_id):
            calls.append(("delete", f'file_id == "{file_id}"'))
            return {}

    async def fake_get_bytes(key):
        assert key == "files/t/202611/1/abc.txt"
        return "你好，这是用于验证入库链路的中文文本内容，重复多遍。\n\n" .encode("utf-8") * 20

    async def fake_status(ids, status, *, tenant_id=None):
        calls.append(("status", status, ids, tenant_id))
        return 1

    monkeypatch.setattr(indexing, "app_state", SimpleNamespace(milvus_store=FakeStore()))
    monkeypatch.setattr(indexing, "get_object_bytes", fake_get_bytes)
    monkeypatch.setattr(indexing.FileDao, "set_parse_status", staticmethod(fake_status))

    written = await indexing.index_document(
        file_id=9, object_key="files/t/202611/1/abc.txt",
        file_ext=".txt", tenant_id=7, file_name="abc.txt",
    )
    assert written > 0
    assert any(c[0] == "delete" and 'file_id == "9"' in c[1] for c in calls)
    assert ("status", "parsed", [9], 7) in calls
    assert any(c[0] == "add" and c[1] == written for c in calls)
