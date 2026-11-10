"""模拟面试图：上下文 → 阶段判断 → 回答评估 → 面试官回应/报告 → 记忆。"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from backend.agents.interview.nodes import (
    check_stage_node,
    evaluate_answer_node,
    generate_report_node,
    generate_response_node,
    load_context_node,
    save_memory_node,
    save_report_node,
)
from backend.agents.interview.state import InterviewStage, InterviewState
from backend.app_state import app_state


def _route_after_check_stage(state: InterviewState) -> str:
    """已结束走报告路径，否则继续本轮问答。"""
    if state.get("current_stage") == InterviewStage.FINISHED.value:
        return "generate_report"
    return "evaluate_answer"


def build_interview_graph():
    """构建模拟面试工作流，绑定项目统一的 Postgres checkpointer。

    拓扑：
        START → load_context → check_stage
          ├─ finished → generate_report → save_report → save_memory → END
          └─ else     → evaluate_answer → generate_response → save_memory → END
    """
    builder = StateGraph(InterviewState)

    builder.add_node("load_context", load_context_node)
    builder.add_node("check_stage", check_stage_node)
    builder.add_node("evaluate_answer", evaluate_answer_node)
    builder.add_node("generate_response", generate_response_node)
    builder.add_node("generate_report", generate_report_node)
    builder.add_node("save_report", save_report_node)
    builder.add_node("save_memory", save_memory_node)

    builder.add_edge(START, "load_context")
    builder.add_edge("load_context", "check_stage")
    builder.add_conditional_edges(
        "check_stage",
        _route_after_check_stage,
        {
            "generate_report": "generate_report",
            "evaluate_answer": "evaluate_answer",
        },
    )
    builder.add_edge("evaluate_answer", "generate_response")
    builder.add_edge("generate_response", "save_memory")
    builder.add_edge("generate_report", "save_report")
    builder.add_edge("save_report", "save_memory")
    builder.add_edge("save_memory", END)

    return builder.compile(checkpointer=app_state.checkpointer)
