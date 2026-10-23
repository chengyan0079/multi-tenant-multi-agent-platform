"""面试图：状态机推进（init→question↔evaluate→report→done，SSE 多轮）。"""
from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from backend.agents.interview.nodes import (
    ask,
    evaluate,
    init_session,
    make_report,
    respond,
    route_stage,
)
from backend.agents.interview.state import InterviewState


def build_interview_graph() -> Any:
    from backend.app_state import app_state

    builder = StateGraph(InterviewState)
    builder.add_node("init_session", init_session)
    builder.add_node("ask", ask)
    builder.add_node("evaluate", evaluate)
    builder.add_node("respond", respond)
    builder.add_node("make_report", make_report)

    builder.add_edge(START, "init_session")
    builder.add_edge("init_session", "ask")
    # 状态机循环：提问→评估→回应→（条件）继续或报告
    builder.add_edge("ask", "evaluate")
    builder.add_edge("evaluate", "respond")
    builder.add_conditional_edges("respond", route_stage, {"ask": "ask", "make_report": "make_report"})
    builder.add_edge("make_report", END)

    return builder.compile(checkpointer=app_state.checkpointer)
