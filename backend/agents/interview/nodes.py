"""面试节点：初始化/提问/评估/回应/报告。"""
from __future__ import annotations

from backend.agents.interview.state import InterviewState
from backend.observability.tracing import tracing


async def init_session(state: InterviewState) -> InterviewState:
    """会话初始化。"""
    tracing.event("interview.init")
    return {"stage": "question", "history": []}


async def ask(state: InterviewState) -> InterviewState:
    """面试官按人设提问（interviewer_persona 插件）。"""
    tracing.event("interview.ask")
    return {"stage": "evaluate"}


async def evaluate(state: InterviewState) -> InterviewState:
    """回答质量评估（interview_evaluator 插件）。"""
    tracing.event("interview.evaluate")
    return {"quality": 0.0, "stage": "question"}


async def respond(state: InterviewState) -> InterviewState:
    """面试官回应并推进阶段。"""
    tracing.event("interview.respond")
    return {"stage": "question"}


async def make_report(state: InterviewState) -> InterviewState:
    """报告生成（interview_report_pdf 插件）。"""
    tracing.event("interview.report")
    return {"report": "", "stage": "done"}


def route_stage(state: InterviewState) -> str:
    """条件边：按 stage 推进状态机；达标进入报告，否则继续提问。"""
    if state.get("stage") == "report":
        return "make_report"
    return "ask"
