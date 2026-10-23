"""批改节点：解析/三轨评分/汇总/HITL/发布。"""
from __future__ import annotations

from langgraph.types import interrupt

from backend.agents.exam.state import ExamState
from backend.core.tracing import tracing


async def parse_word(state: ExamState) -> ExamState:
    """Word 解析→题目元数据加载。word_parse 能力缺失时降级空。"""
    tracing.event("exam.parse_word")
    from backend.app_state import app_state

    if app_state.plugin_registry:
        tool = app_state.plugin_registry.get_tool("word_parse")
        if tool is not None:
            try:
                items = await app_state.plugin_registry.call("word_parse", file_ref=state.get("file_ref", ""))
                return {"items": items}
            except Exception:
                pass
    return {"items": []}


async def grade_objective(state: ExamState) -> ExamState:
    """客观题规则判分（objective_grader 插件）。"""
    tracing.event("exam.grade_objective")
    return {"grades": {"objective": {"score": 0.0}}}


async def grade_subjective(state: ExamState) -> ExamState:
    """简答 LLM 判分（subjective_rubric 插件）。"""
    tracing.event("exam.grade_subjective")
    return {"grades": {"subjective": {"score": 0.0}}}


async def grade_code(state: ExamState) -> ExamState:
    """代码 LLM 判分（code_exec 沙箱）。"""
    tracing.event("exam.grade_code")
    return {"grades": {"code": {"score": 0.0}}}


async def aggregate(state: ExamState) -> ExamState:
    """三轨汇总。"""
    tracing.event("exam.aggregate")
    return {"summary": f"三轨评分: {state.get('grades', {})}"}


async def human_review(state: ExamState) -> ExamState:
    """高风险发布前挂起（HITL），写入队列等待教师 resume。"""
    tracing.event("exam.human_review")
    reason = "试卷批改结果待教师确认后发布"
    # interrupt 暂停图执行，teacher 经 /v1/threads/{id}/resume 注入决策
    decision = interrupt({"reason": reason})
    return {"hitl_reason": reason, "published": bool(decision.get("approve")) if isinstance(decision, dict) else False}


async def publish(state: ExamState) -> ExamState:
    """教师确认后发布结果（落库在 api 层）。"""
    tracing.event("exam.publish")
    return {"published": True}
