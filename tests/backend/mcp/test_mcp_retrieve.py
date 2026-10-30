"""mcp_client 纯函数单测：SSE 解析与 chunk 字段映射（不连网、不依赖 MCP 服务）。"""
from __future__ import annotations

from backend.mcp.retrieval.mcp_client import _parse_sse_chunks, _to_adapter_item


def test_parse_sse_chunks_extracts_only_chunk_events() -> None:
    text = (
        "event: meta\ndata: {\"query\":\"q\",\"total\":2}\n\n"
        "event: chunk\n"
        "data: {\"content\":\"a\",\"doc_name\":\"d1\",\"page\":1,\"score\":0.9,\"chunk_id\":10}\n\n"
        "event: chunk\n"
        "data: {\"content\":\"b\",\"doc_name\":\"d2\",\"page\":2,\"score\":0.8}\n\n"
        "event: done\ndata: {}\n\n"
    )
    chunks = _parse_sse_chunks(text)
    assert len(chunks) == 2
    assert chunks[0]["content"] == "a"
    assert chunks[1]["score"] == 0.8


def test_parse_sse_chunks_skips_bad_json() -> None:
    text = "event: chunk\ndata: not-json\n\n"
    assert _parse_sse_chunks(text) == []


def test_to_adapter_item_maps_fields() -> None:
    item = _to_adapter_item({
        "content": "x", "doc_name": "doc", "page": 3,
        "score": 0.5, "chunk_id": 1, "parent_id": 0,
    })
    assert item["content"] == "x"
    assert item["score"] == 0.5
    assert item["source"] == "doc#p3"
    assert item["metadata"]["doc_name"] == "doc"
    assert item["metadata"]["page"] == 3


def test_to_adapter_item_without_doc_name() -> None:
    item = _to_adapter_item({"content": "x", "page": 5, "score": 0.1})
    assert item["source"] == "p5"
