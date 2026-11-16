"""父子片存储与生成节点上下文组装单测（不连真实 Milvus / LLM）。"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.data.milvus.store import DocumentMilvusStore


def test_schema_declares_parent_child_and_extra_fields() -> None:
    schema = DocumentMilvusStore().build_schema()
    names = {f.name for f in schema.fields}
    assert {"parent_id", "parent_content", "chunk_type", "source_location", "extra"} <= names
    assert "parent_content" in DocumentMilvusStore.OUTPUT_FIELDS
    assert "extra" in DocumentMilvusStore.OUTPUT_FIELDS


@pytest.mark.asyncio
async def test_add_chunks_writes_parent_fields(monkeypatch) -> None:
    from backend.data.milvus import store as store_mod

    captured: list[list[dict]] = []

    class FakeClient:
        async def upsert(self, *, collection_name, data):
            captured.append(data)
            return {"upsert_count": len(data)}

    class FakeFactory:
        async def embed(self, texts):
            return {
                "dense": [[1.0, 0.0] for _ in texts],
                "sparse": [{} for _ in texts],
            }

    monkeypatch.setattr(store_mod, "app_state", SimpleNamespace(
        settings=SimpleNamespace(milvus=SimpleNamespace(collection="agent_rag_docs", dense_dim=2)),
        llm_factory=FakeFactory(),
    ))
    s = DocumentMilvusStore(client=FakeClient())
    rows = [{
        "text": "核心结论", "tenant_id": "7", "file_id": "9", "file_name": "a.txt",
        "parent_id": "9:parent:0", "parent_content": "前言核心结论后记",
        "chunk_type": "child", "chunk_index": 0, "child_index": 0,
        "page": 1, "source_location": "a.txt > 第 1 页",
        "extra": {"doc_type": "txt", "file_hash": "abc"},
    }]
    assert await s.add_chunks(rows) == 1
    row = captured[0][0]
    assert row["chunk_id"] == "9:parent:0:child:0"
    assert row["parent_id"] == "9:parent:0"
    assert row["parent_content"] == "前言核心结论后记"
    assert row["content"] == "核心结论"
    assert row["extra"]["doc_type"] == "txt"
    assert "dense" in row and "sparse" in row


@pytest.mark.asyncio
async def test_ensure_collection_rejects_old_schema(monkeypatch) -> None:
    from backend.data.milvus import store as store_mod

    class FakeClient:
        async def has_collection(self, name):
            return True

        async def describe_collection(self, name):
            return {"fields": [{"name": "chunk_id"}, {"name": "content"}]}

        async def load_collection(self, name):
            return None

    monkeypatch.setattr(store_mod, "app_state", SimpleNamespace(
        settings=SimpleNamespace(milvus=SimpleNamespace(collection="agent_rag_docs", dense_dim=2)),
    ))
    s = DocumentMilvusStore(client=FakeClient())
    with pytest.raises(RuntimeError, match="旧 schema"):
        await s.ensure_collection()


@pytest.mark.asyncio
async def test_generate_rag_uses_highlight_and_dedups_parent(monkeypatch) -> None:
    from backend.agents.qa import nodes as qa_nodes
    from backend.agents.qa.state import RankedChunk

    seen: dict = {}

    class FakeChain:
        async def ainvoke(self, payload):
            seen.update(payload)
            return "答案"

    class _P:
        def __or__(self, other):
            # prompt | llm 先返回 _P，再 | StrOutputParser() 才得到可 ainvoke 的 chain
            return _P()

        async def ainvoke(self, payload):
            return await FakeChain().ainvoke(payload)

    class FakePrompt:
        @staticmethod
        def from_messages(_):
            return _P()

    async def fake_get_llm(_, *, thinking=False):
        return object()

    monkeypatch.setattr(qa_nodes, "ChatPromptTemplate", FakePrompt)
    monkeypatch.setattr(qa_nodes, "StrOutputParser", lambda: object())
    monkeypatch.setattr(qa_nodes, "get_llm", fake_get_llm)
    monkeypatch.setattr(qa_nodes, "config", SimpleNamespace(
        qa=SimpleNamespace(parent_context_by_highlight=True, summary_trigger_turns=6),
    ))

    state = {
        "ranked_chunks": [
            RankedChunk(content="A", score=0.9, source="a.txt",
                        parent_id="9:parent:0", highlighted_content="前言<mark>A</mark>后记"),
            # 同父片的另一子片：应被去重，不重复进上下文
            RankedChunk(content="B", score=0.8, source="a.txt",
                        parent_id="9:parent:0", highlighted_content="前言<mark>B</mark>后记"),
        ],
        "original_query": "问题", "messages": [], "existing_summary": None,
    }
    out = await qa_nodes.generate_rag_node(state)
    context = seen["context"]
    assert "【参考1】" in context
    assert "【参考2】" not in context
    assert "<mark>A</mark>" in context
    assert "<mark>B</mark>" not in context
    assert "前言" in context and "后记" in context
    assert out["answer_mode"] == "rag"
