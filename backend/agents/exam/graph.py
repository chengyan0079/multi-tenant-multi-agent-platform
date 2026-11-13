"""试卷批阅工作流图：解析→三轨批改→汇总→薄弱点→HITL 复核→发布，thread_id=submission_id。"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from backend.agents.exam.nodes import (
    aggregate_results_node,
    analyze_weak_points_node,
    apply_teacher_decision_node,
    load_questions_meta_node,
    notify_teacher_node,
    parse_word_node,
    publish_results_node,
    run_three_tracks_node,
    teacher_review_node,
)
from backend.agents.exam.state import ExamState
from backend.app_state import app_state


def build_exam_graph():
    """构建并编译试卷批阅工作流图（绑定项目统一 checkpointer）。"""
    builder = StateGraph(ExamState)

    builder.add_node("parse_word", parse_word_node)
    builder.add_node("load_questions_meta", load_questions_meta_node)
    builder.add_node("run_three_tracks", run_three_tracks_node)
    builder.add_node("aggregate_results", aggregate_results_node)
    builder.add_node("analyze_weak_points", analyze_weak_points_node)
    builder.add_node("notify_teacher", notify_teacher_node)
    builder.add_node("teacher_review", teacher_review_node)
    builder.add_node("apply_teacher_decision", apply_teacher_decision_node)
    builder.add_node("publish_results", publish_results_node)

    builder.add_edge(START, "parse_word")
    builder.add_edge("parse_word", "load_questions_meta")
    builder.add_edge("load_questions_meta", "run_three_tracks")
    builder.add_edge("run_three_tracks", "aggregate_results")
    builder.add_edge("aggregate_results", "analyze_weak_points")
    builder.add_edge("analyze_weak_points", "notify_teacher")
    builder.add_edge("notify_teacher", "teacher_review")
    builder.add_edge("teacher_review", "apply_teacher_decision")
    builder.add_edge("apply_teacher_decision", "publish_results")
    builder.add_edge("publish_results", END)

    return builder.compile(checkpointer=app_state.checkpointer)


if __name__ == "__main__":
    graph = build_exam_graph()
    # print(graph.get_graph().draw_mermaid())
    graph.get_graph().draw_png("exam_graph.png")
