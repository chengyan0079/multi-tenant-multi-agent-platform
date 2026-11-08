"""graph - 试卷批阅工作流图

流水线：
    START
      → parse_word             解析学员作答 Word 文件
      → load_questions_meta    加载 DB 题目元数据并与学员答案合并
      → run_three_tracks       三轨并行批改（客观题 / 简答题 / 代码题）
      → aggregate_results      汇总三轨结果，算总分、得分率、需复核数
      → analyze_weak_points    分析知识薄弱点并生成复习建议
      → notify_teacher         把提交状态置为 pending_review
      → teacher_review         调用 interrupt() 暂停，等待教师确认
      → apply_teacher_decision 合并教师修改，得到最终分数
      → publish_results        写入 agent_exam_reviews 并发布
      → END

说明：
    teacher_review 是暂停点：checkpointer 在暂停时保存状态，教师确认后 API 用
    Command(resume=decision) 让图从暂停处继续执行。checkpointer 使用项目统一的
    app_state.checkpointer（AsyncPostgresSaver），与 qa 等一致；thread_id 即
    submission_id，保证 broker 消费跑图与教师 confirm 恢复指向同一份中断状态。
"""
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
    print(graph.get_graph().draw_mermaid())
