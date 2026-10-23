"""问答图：分类→检索→生成→(低置信) Web 兜底（设计文档 §0.1）。"""
from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from backend.agents.qa.nodes import classify, generate, retrieve, route_by_confidence, web_fallback
from backend.agents.qa.state import QAState


def build_qa_graph() -> Any:
    from backend.app_state import app_state

    builder = StateGraph(QAState)
    builder.add_node("classify", classify)
    builder.add_node("retrieve", retrieve)
    builder.add_node("generate", generate)
    builder.add_node("web_fallback", web_fallback)

    builder.add_edge(START, "classify")
    builder.add_edge("classify", "retrieve")
    builder.add_edge("retrieve", "generate")
    # 条件边：按置信度决定兜底或结束
    builder.add_conditional_edges("generate", route_by_confidence, {"web_fallback": "web_fallback", "end": END})
    builder.add_edge("web_fallback", END)

    return builder.compile(checkpointer=app_state.checkpointer)
