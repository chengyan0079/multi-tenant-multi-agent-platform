"""问答节点：意图分类/检索/生成/Web 兜底/记忆。"""
from __future__ import annotations

from backend.agents.qa.state import QAState
from backend.app_state import app_state, get_tenant_id
from backend.common.llm.llm_factory import LLMFactory
from backend.observability.tracing import tracing
from backend.mcp.retrieval.adapter import rag_retrieve


async def classify(state: QAState) -> QAState:
    """bert-chinese 意图粗分（快路径），失败降级 general。"""
    tracing.event("qa.classify")
    factory: LLMFactory = app_state.llm_factory  # type: ignore[assignment]
    intent = await factory.classify(state.get("query", ""))
    return {"intent": intent}


async def retrieve(state: QAState) -> QAState:
    """rag_retrieve 工具（经 RAG 适配层）。失败降级为空，不阻断生成。"""
    tracing.event("qa.retrieve")
    tenant = state.get("tenant_id") or get_tenant_id() or ""
    try:
        chunks = await rag_retrieve(state.get("query", ""), tenant, top_k=5)
    except Exception:
        chunks = []
    return {"chunks": [c.__dict__ for c in chunks]}


async def generate(state: QAState) -> QAState:
    """按置信度生成；低置信且无 chunks 时标记走 Web 兜底。"""
    tracing.event("qa.generate")
    has_chunks = bool(state.get("chunks"))
    confidence = 0.9 if has_chunks else 0.2
    # 占位：真实接 LLM Factory 生成 + 记忆保存
    return {"confidence": confidence, "answer": "" if not has_chunks else "（已基于知识库生成）"}


async def web_fallback(state: QAState) -> QAState:
    """低置信兜底：联网检索（web_search 能力）。"""
    tracing.event("qa.web_fallback")
    from backend.app_state import app_state as _s

    tool = _s.plugin_registry.get_tool("web_search") if _s.plugin_registry else None
    if tool is not None:
        await _s.plugin_registry.call("web_search", query=state.get("query", ""))
    return {"answer": "（联网兜底结果占位）"}


def route_by_confidence(state: QAState) -> str:
    """条件边：低置信且无知识库命中 → Web 兜底，否则结束。"""
    if state.get("confidence", 1.0) < 0.5 and not state.get("chunks"):
        return "web_fallback"
    return "end"
