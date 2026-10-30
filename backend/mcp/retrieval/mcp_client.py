"""mcp_client - 经对外暴露的 MCP 服务接入检索能力。

检索服务以 FastMCP(streamable-http) 把自身 HTTP API 自动封装为 MCP 工具，
默认地址 http://127.0.0.1:8766/mcp。其检索接口 POST /admin/retrieve 被命名为
工具 post_admin_retrieve；该接口走 SSE 流式返回 chunk 事件，本模块调用工具后
解析 SSE 文本，封装成与包导入模式一致的结构（content/score/source/metadata），
供 adapter.rag_retrieve 零成本复用。

tenant_id 在 agent-platform 中为整数，str() 仅用于序列化成 HTTP 头；检索服务侧按整数
解析并做租户隔离，不会出现非数字导致的 400（与其它接入方式口径一致）。
"""
from __future__ import annotations

import json
from contextlib import AsyncExitStack
from typing import Any, Dict, List

from mcp import ClientSession
from mcp.client.streamable_http import StreamableHTTPTransport

from backend.app_state import app_state
from backend.common.logger import get_logger, trace_id_ctx
from backend.observability.exception import CapabilityError

logger = get_logger("rag_mcp_client")

# 检索 API 在 MCP 服务中自动注册的工具名（POST /admin/retrieve）
_RETRIEVE_TOOL = "post_admin_retrieve"


def _parse_sse_chunks(text: str) -> List[Dict[str, Any]]:
    """解析 SSE 文本，提取所有 event: chunk 的 data JSON。

    事件形如：
        event: chunk
        data: {"content": "...", "doc_name": "...", "page": 1, "score": 0.9}
    非 chunk 事件（meta/done/error）忽略；单行 data 解析失败则跳过该块。
    """
    chunks: List[Dict[str, Any]] = []
    for block in text.split("\n\n"):
        event = data = None
        for line in block.splitlines():
            if line.startswith("event:"):
                event = line[len("event:"):].strip()
            elif line.startswith("data:"):
                data = line[len("data:"):].strip()
        if event == "chunk" and data:
            try:
                chunks.append(json.loads(data))
            except json.JSONDecodeError:
                logger.warning("rag mcp 检索 chunk 解析失败，跳过: %s", data[:200])
    return chunks


def _to_adapter_item(c: Dict[str, Any]) -> Dict[str, Any]:
    """把 SSE chunk 映射成 adapter 期望的字段（content/score/source/metadata）。"""
    doc_name = c.get("doc_name", "")
    page = c.get("page")
    source = doc_name
    if page:
        source = f"{doc_name}#p{page}" if doc_name else f"p{page}"
    return {
        "content": c.get("content", ""),
        "score": float(c.get("score", 0.0)),
        "source": source,
        "metadata": {
            "doc_name": doc_name,
            "page": page,
            "chunk_id": c.get("chunk_id"),
            "parent_id": c.get("parent_id"),
        },
    }


async def mcp_retrieve(
    query: str, tenant_id: int, top_k: int = 5, scope: str = "doc",
) -> List[Dict[str, Any]]:
    """经对外暴露的 MCP 服务调用 post_admin_retrieve，返回统一的 chunk 列表。

    每次调用临时建立 MCP 会话（无状态、跨请求不共享），连接开销在本地 8766 可接受；
    后续若需复用长连接再缓存 transport。工具返回错误或非预期结构时抛 CapabilityError，
    由上层 adapter 捕获降级（不阻断生成链路）。
    """
    cfg = app_state.settings.rag
    if not cfg.mcp_url:
        raise CapabilityError("RAG MCP 未配置（RAG_MCP_URL 为空）", degradable=True)
    try:
        async with AsyncExitStack() as stack:
            transport = await stack.enter_async_context(
                StreamableHTTPTransport(url=cfg.mcp_url))
            session = await stack.enter_async_context(ClientSession(transport))
            await session.initialize()
            result = await session.call_tool(
                _RETRIEVE_TOOL,
                {
                    "body": {"query": query, "scope": scope, "top_k": top_k, "rerank": True},
                    "headers": {
                        "X-Tenant-Id": str(tenant_id),
                        "X-Trace-Id": trace_id_ctx.get() or "",
                    },
                },
            )
    except CapabilityError:
        raise
    except Exception as exc:  # noqa: BLE001 - 连接 / 握手 / 协议异常统一兜底
        raise CapabilityError(f"RAG MCP 调用失败: {exc}", degradable=True) from exc

    if getattr(result, "isError", False):
        raise CapabilityError(f"RAG MCP 工具返回错误: {result}", degradable=True)
    text = result.content[0].text if result.content else ""
    raw = _parse_sse_chunks(text)
    return [_to_adapter_item(c) for c in raw]
