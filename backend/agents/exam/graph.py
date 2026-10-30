"""批改图：解析→三轨并行→汇总→HITL→发布（设计文档 §0.1 / §3.4）。"""
from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from backend.agents.exam.nodes import (
    aggregate,
    grade_code,
    grade_objective,
    grade_subjective,
    human_review,
    parse_word,
    publish,
)
from backend.agents.exam.state import ExamState


def build_exam_graph() -> Any:
    from backend.app_state import app_state

    # todo 图待定
    builder = StateGraph(ExamState)
    # builder.add_node("parse_word", parse_word)
    # builder.add_node("grade_objective", grade_objective)
    # builder.add_node("grade_subjective", grade_subjective)
    # builder.add_node("grade_code", grade_code)
    # builder.add_node("aggregate", aggregate)
    # builder.add_node("human_review", human_review)
    # builder.add_node("publish", publish)
    #
    # builder.add_edge(START, "parse_word")
    # # 三轨并行 fan-out
    # builder.add_edge("parse_word", "grade_objective")
    # builder.add_edge("parse_word", "grade_subjective")
    # builder.add_edge("parse_word", "grade_code")
    # # fan-in 汇总
    # builder.add_edge("grade_objective", "aggregate")
    # builder.add_edge("grade_subjective", "aggregate")
    # builder.add_edge("grade_code", "aggregate")
    # # HITL 暂停恢复
    # builder.add_edge("aggregate", "human_review")
    # builder.add_edge("human_review", "publish")
    # builder.add_edge("publish", END)

    return builder.compile(checkpointer=app_state.checkpointer)
