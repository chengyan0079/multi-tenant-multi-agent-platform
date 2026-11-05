"""问答图：分类 → (HyDE / Multi-Query) → 检索 → 生成 → (低置信) Web 兜底 → 记忆。

图结构与参考项目 agents/qa/graph.py 完全一致；唯一差异是 checkpointer 取自本项目的
app_state.checkpointer（AsyncPostgresSaver），并在节点内部完成参考项目中由 core 模块承担的
检索/记忆职责。
"""
from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from backend.agents.qa.nodes import (
    classify_query_node,
    enqueue_pending_node,
    generate_direct_node,
    generate_general_node,
    generate_rag_node,
    hyde_generate_node,
    multi_query_rewrite_node,
    retrieve_node,
    save_memory_node,
    web_search_node,
)
from backend.agents.qa.state import QAState
from backend.app_state import app_state


def _route_by_query_type(state: QAState) -> str:
    """classify_query 之后的路由：按 query_type 与 enable_web_search 分流。"""
    qt = state.get("query_type", "PRECISE").upper()
    if qt == "GENERAL" and state.get("enable_web_search", False):
        return "GENERAL_WEB"
    return qt


def _route_by_confidence(state: QAState) -> str:
    """retrieve 之后的路由：按置信度和联网开关分流。"""
    if state.get("is_high_confidence", False):
        return "high"
    if state.get("enable_web_search", False):
        return "low_web"
    return "low_direct"


def _route_after_web_search(state: QAState) -> str:
    """web_search 节点被两条路径共用，走完搜索后需要区分去向。"""
    if state.get("query_type", "").upper() == "GENERAL":
        return "generate_general"
    return "generate_direct"


def build_qa_graph():
    """构建知识问答工作流并绑定 checkpointer。"""
    builder = StateGraph(QAState)

    builder.add_node("classify_query", classify_query_node)
    builder.add_node("hyde_generate", hyde_generate_node)
    builder.add_node("multi_query_rewrite", multi_query_rewrite_node)
    builder.add_node("retrieve", retrieve_node)
    builder.add_node("generate_rag", generate_rag_node)
    builder.add_node("web_search", web_search_node)
    builder.add_node("generate_direct", generate_direct_node)
    builder.add_node("generate_general", generate_general_node)
    builder.add_node("enqueue_pending", enqueue_pending_node)
    builder.add_node("save_memory", save_memory_node)

    builder.add_edge(START, "classify_query")

    builder.add_conditional_edges(
        "classify_query",
        _route_by_query_type,
        {
            "GENERAL": "generate_general",
            "GENERAL_WEB": "web_search",
            "PRECISE": "retrieve",
            "VAGUE": "hyde_generate",
            "BROAD": "multi_query_rewrite",
        },
    )

    builder.add_edge("hyde_generate", "retrieve")
    builder.add_edge("multi_query_rewrite", "retrieve")

    builder.add_conditional_edges(
        "retrieve",
        _route_by_confidence,
        {
            "high": "generate_rag",
            "low_web": "web_search",
            "low_direct": "generate_direct",
        },
    )

    builder.add_conditional_edges(
        "web_search",
        _route_after_web_search,
        {
            "generate_general": "generate_general",
            "generate_direct": "generate_direct",
        },
    )

    builder.add_edge("generate_rag", "save_memory")
    builder.add_edge("generate_general", "save_memory")
    builder.add_edge("generate_direct", "enqueue_pending")
    builder.add_edge("enqueue_pending", "save_memory")
    builder.add_edge("save_memory", END)

    return builder.compile(checkpointer=app_state.checkpointer)
