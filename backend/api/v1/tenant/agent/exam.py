"""试卷批改接口：学员提交 Word 试卷触发异步三轨批改，教师复核后发布。"""

from __future__ import annotations

import asyncio
import json

import uuid6
from fastapi import APIRouter, Depends, File, Form, HTTPException, status, UploadFile
from langgraph.types import Command
from pydantic import BaseModel, TypeAdapter
from sqlalchemy import text

from backend.app_state import app_state
from backend.broker.publish import enqueue_task
from backend.broker.types import TaskType
from backend.common.logger import get_logger
from backend.common.response import success
from backend.config import config
from backend.agents.exam.state import PreReviewSummary, WeakPoint
from backend.data.clients.minio import build_object_key, get_storage
from backend.data.sql import session_scope
from backend.middleware.auth import CurrentUser, get_current_user
from backend.security.rbac import Scope
from backend.security.security import require_scope

logger = get_logger("exam_api")

router = APIRouter(prefix="/exam", tags=["exam"])

# 懒加载图：确保 app_state.checkpointer 就绪后再编译
_graph = None


def _get_graph():
    global _graph
    if _graph is None:
        from backend.agents.exam.graph import build_exam_graph

        _graph = build_exam_graph()
    return _graph


class ConfirmRequest(BaseModel):
    action: str
    modifications: list[dict] = []


@router.get("/my-submissions")
async def list_my_submissions(
    _: object = Depends(require_scope(Scope.EXAM_PAGE)),  # noqa: B008
    current: CurrentUser = Depends(get_current_user),
) -> dict:
    """当前用户最近的提交记录（最多 20 条）。

    请求：无
    权限：exam:page
    返回：items[{ submission_id, exam_id, exam_title, status, submitted_at }]
    """
    async with session_scope() as session:
        rows = (
            (
                await session.execute(
                    text(
                        """
                    SELECT es.id, e.title, es.exam_id, es.status, es.submitted_at
                      FROM agent_exam_submissions es
                      LEFT JOIN agent_exams e ON e.id = es.exam_id
                     WHERE es.user_id = :user_id
                     ORDER BY es.submitted_at DESC
                     LIMIT 20
                    """
                    ),
                    {"user_id": current.user_id},
                )
            )
            .mappings()
            .all()
        )
    return success(
        {
            "items": [
                {
                    "submission_id": str(r["id"]),
                    "exam_id": str(r["exam_id"]),
                    "exam_title": r["title"] or "",
                    "status": r["status"],
                    "submitted_at": r["submitted_at"].isoformat() if r["submitted_at"] else None,
                }
                for r in rows
            ]
        }
    )


@router.get("/my-submissions/{submission_id}")
async def get_my_submission(
    submission_id: str,
    _: object = Depends(require_scope(Scope.EXAM_VIEW)),  # noqa: B008
    current: CurrentUser = Depends(get_current_user),
) -> dict:
    """获取本人提交详情；未发布时只返回状态。

    说明：published 后返回逐题评分、总分与薄弱点。
    请求：path { submission_id }
    权限：exam:view
    返回：status / pre_review_summary / weak_points / weak_points_summary
    """
    async with session_scope() as session:
        row = (
            (
                await session.execute(
                    text(
                        """
                    SELECT id, status, weak_points, weak_points_summary
                      FROM agent_exam_submissions
                     WHERE id = :sid AND user_id = :user_id
                    """
                    ),
                    {"sid": submission_id, "user_id": current.user_id},
                )
            )
            .mappings()
            .first()
        )
        if not row:
            raise HTTPException(status_code=404, detail="提交记录不存在")

        if row["status"] != "published":
            return success({"submission_id": submission_id, "status": row["status"]})

        reviews = (
            (
                await session.execute(
                    text(
                        """
                    SELECT er.question_id, er.question_type, er.knowledge_tag,
                           er.student_answer, er.ai_score, er.ai_feedback,
                           er.teacher_score, er.teacher_comment, er.final_score,
                           er.needs_review, er.ai_raw_result,
                           q.question_no, q.content, q.correct_answer, q.score AS full_score
                      FROM agent_exam_reviews er
                      JOIN agent_questions q ON q.id = er.question_id
                     WHERE er.submission_id = :sid
                     ORDER BY q.question_no
                    """
                    ),
                    {"sid": submission_id},
                )
            )
            .mappings()
            .all()
        )

    by_question = []
    total_score = 0
    full_score_total = 0
    for r in reviews:
        raw = r["ai_raw_result"] or {}
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except Exception:
                raw = {}
        final = r["final_score"] if r["final_score"] is not None else r["ai_score"]
        by_question.append(
            {
                "question_id": str(r["question_id"]),
                "question_no": r["question_no"],
                "question_type": r["question_type"],
                "full_score": r["full_score"],
                "score": r["ai_score"],
                "final_score": final,
                "student_answer": r["student_answer"] or "",
                "correct_answer": r["correct_answer"] or "",
                "ai_feedback": r["ai_feedback"] or "",
                "teacher_comment": r["teacher_comment"] or "",
                "needs_review": r["needs_review"],
                "point_results": raw.get("point_results", []),
                "quality_feedback": raw.get("quality_feedback", []),
            }
        )
        total_score += final or 0
        full_score_total += r["full_score"] or 0

    return success(
        {
            "submission_id": submission_id,
            "status": "published",
            "pre_review_summary": {
                "total_score": total_score,
                "full_score": full_score_total,
                "score_rate": round(total_score / full_score_total, 4) if full_score_total else 0,
                "by_question": by_question,
            },
            "weak_points": row["weak_points"] if isinstance(row["weak_points"], list) else [],
            "weak_points_summary": row["weak_points_summary"] or "",
        }
    )


@router.get("/pending-reviews")
async def get_pending_reviews(
    _: object = Depends(require_scope(Scope.EXAM_REVIEW)),  # noqa: B008
    current: CurrentUser = Depends(get_current_user),
) -> dict:
    """教师待复核列表（本租户 pending_review 提交）。

    请求：无
    权限：exam:review
    返回：items[{ submission_id, student_name, exam_title, submitted_at, pre_review, weak_points }]
    """
    async with session_scope() as session:
        rows = (
            await session.execute(
                text(
                    """
                    SELECT es.id, es.user_id, u.username AS student_name,
                           e.title AS exam_title, es.submitted_at
                      FROM agent_exam_submissions es
                      JOIN agent_user u ON u.id = es.user_id
                      JOIN agent_exams e ON e.id = es.exam_id
                     WHERE u.tenant_id = :tenant_id AND es.status = 'pending_review'
                     ORDER BY es.submitted_at DESC
                    """
                ),
                {"tenant_id": current.tenant_id},
            )
        ).mappings().all()

    items = []
    for row in rows:
        submission_id = str(row["id"])
        pre_review = {"total_score": 0, "full_score": 0, "needs_review_count": 0}
        weak_points: list[dict] = []
        try:
            state_snap = await _get_graph().aget_state({"configurable": {"thread_id": submission_id}})
            if state_snap and state_snap.values:
                sv = state_snap.values
                raw_summary = sv.get("pre_review_summary")
                summary_model = (
                    TypeAdapter(PreReviewSummary).validate_python(raw_summary)
                    if raw_summary
                    else None
                )
                pre_review = {
                    "total_score": summary_model.total_score if summary_model else 0,
                    "full_score": summary_model.full_score if summary_model else 0,
                    "needs_review_count": summary_model.needs_review_count if summary_model else 0,
                }
                raw_wp = sv.get("weak_points")
                weak_points = (
                    [wp.model_dump() for wp in TypeAdapter(list[WeakPoint]).validate_python(raw_wp)]
                    if raw_wp
                    else []
                )
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "exam.pending_review_state_read_failed",
                submission_id=submission_id,
                error=str(e),
            )

        items.append(
            {
                "submission_id": submission_id,
                "student_name": row["student_name"],
                "exam_title": row["exam_title"],
                "submitted_at": row["submitted_at"].isoformat() if row["submitted_at"] else None,
                "pre_review": pre_review,
                "weak_points": weak_points[:3],
            }
        )

    return success({"items": items, "total": len(items)})


@router.get("/submissions/{submission_id}/review")
async def get_submission_review(
    submission_id: str,
    _: object = Depends(require_scope(Scope.EXAM_REVIEW)),  # noqa: B008
    current: CurrentUser = Depends(get_current_user),
) -> dict:
    """教师获取待复核快照：预评摘要与薄弱点。

    说明：读取 checkpointer 中 pending_review 状态的数据，供教师确认/修改。
    请求：path { submission_id }
    权限：exam:review
    返回：student_id / pre_review_summary / weak_points / weak_points_summary
    """
    state_snap = await _get_graph().aget_state({"configurable": {"thread_id": submission_id}})
    if not state_snap or not state_snap.values:
        raise HTTPException(status_code=404, detail="批改尚未完成或记录不存在")
    sv = state_snap.values
    raw_summary = sv.get("pre_review_summary")
    summary_model = (
        TypeAdapter(PreReviewSummary).validate_python(raw_summary) if raw_summary else None
    )
    raw_wp = sv.get("weak_points", [])
    weak_points = (
        [wp.model_dump() for wp in TypeAdapter(list[WeakPoint]).validate_python(raw_wp)]
        if raw_wp
        else []
    )
    return success(
        {
            "submission_id": submission_id,
            "student_id": sv.get("student_id", ""),
            "pre_review_summary": summary_model.model_dump() if summary_model else {},
            "weak_points": weak_points,
            "weak_points_summary": sv.get("weak_points_summary", ""),
        }
    )


@router.post("/submissions/{submission_id}/confirm")
async def confirm_review(
    submission_id: str,
    req: ConfirmRequest,
    _: object = Depends(require_scope(Scope.EXAM_REVIEW)),  # noqa: B008
    current: CurrentUser = Depends(get_current_user),
) -> dict:
    """教师确认/修改批改结果并发布。

    说明：校验状态为 pending_review 后，经 Orchestrator.resume 注入决策，跑完发布。
    请求：path { submission_id }, body { action: 'approve'|'modify', modifications?: list }
    权限：exam:review
    返回：status / final_score / full_score / score_rate / weak_points
    """
    if req.action not in ("approve", "modify"):
        raise HTTPException(status_code=400, detail="action 只能为 approve 或 modify")

    async with session_scope() as session:
        rec = (
            (
                await session.execute(
                    text("SELECT status FROM agent_exam_submissions WHERE id = :sid"),
                    {"sid": submission_id},
                )
            )
            .mappings()
            .first()
        )
        if not rec:
            raise HTTPException(status_code=404, detail="提交记录不存在")
        if rec["status"] != "pending_review":
            raise HTTPException(status_code=409, detail=f"当前状态 {rec['status']} 不可确认")

    decision = {
        "action": req.action,
        "modifications": req.modifications,
        "teacher_id": current.user_id,
    }

    orch = app_state.orchestrator
    if orch is None:
        raise HTTPException(status_code=503, detail="编排器未就绪")

    try:
        result = await orch.resume("exam", submission_id, Command(resume=decision))
    except Exception as e:
        logger.exception("exam.confirm_failed", submission_id=submission_id, error=str(e))
        raise HTTPException(status_code=500, detail=f"发布失败：{e}")

    structured = result.get("structured_output", {}) or {}
    return success(
        {
            "submission_id": submission_id,
            "status": "published",
            "final_score": structured.get("final_score", 0),
            "full_score": structured.get("full_score", 0),
            "score_rate": structured.get("score_rate", 0),
            "weak_points": structured.get("weak_points", []),
            "weak_points_summary": structured.get("weak_points_summary", ""),
        }
    )
