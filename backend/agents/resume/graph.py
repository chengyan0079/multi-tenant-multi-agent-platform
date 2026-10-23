"""简历审查图：六维度并行 fan-out → 诊断 → 报告（设计文档 §0.1）。"""
from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from backend.agents.resume.nodes import (
    build_report,
    diagnose,
    make_scorer,
    parse_pdf,
)
from backend.agents.resume.state import ResumeState, _DIMENSIONS


def build_resume_graph() -> Any:
    """构造并编译简历审查图；绑定 app_state.checkpointer 支持多轮持久化。"""
    from backend.app_state import app_state

    builder = StateGraph(ResumeState)
    builder.add_node("parse_pdf", parse_pdf)
    for dim in _DIMENSIONS:
        builder.add_node(f"score_{dim}", make_scorer(dim))
    builder.add_node("diagnose", diagnose)
    builder.add_node("build_report", build_report)

    builder.add_edge(START, "parse_pdf")
    # fan-out：解析后并行打分
    for dim in _DIMENSIONS:
        builder.add_edge("parse_pdf", f"score_{dim}")
        builder.add_edge(f"score_{dim}", "diagnose")
    # fan-in：诊断节点在六维度都到达后汇总（LangGraph 自动等待前驱）
    builder.add_edge("diagnose", "build_report")
    builder.add_edge("build_report", END)

    checkpointer = app_state.checkpointer
    return builder.compile(checkpointer=checkpointer)
