"""统一任务型入口：exam/resume 两阶段第二步——建业务行 + 入队（§4.5 / §4.6）。

由 DefaultAgentAdapter.on_first_turn 在 chat/stream 内调用。入队消息 data 携带
turn_id / thread_id / trace_id，broker handler 完成后据此回写一条 task_result turn。
"""
from __future__ import annotations

import json
import uuid6
from typing import Any, Optional

from sqlalchemy import text

from backend.broker.publish import enqueue_task
from backend.broker.types import TaskType
from backend.common.logger import get_logger
from backend.data.sql import session_scope
from backend.orchestration.agent_spec import AgentSpec
from backend.orchestration.unified_schemas import AttachmentRef, EntryPayload

logger = get_logger("unified_task_service")


def _entry_value(entry: Optional[EntryPayload], name: str) -> Optional[str]:
    if not entry or not entry.fields:
        return None
    for f in entry.fields:
        if f.name == name and f.value:
            return str(f.value)
    return None


async def _object_key_of(attachments: list[AttachmentRef]) -> str | None:
    if not attachments:
        return None
    from backend.services.attachment_service import get_attachment_object_key

    return await get_attachment_object_key(attachments[0].file_ref)


async def start_unified_task(
    *,
    spec: AgentSpec,
    turn_id: str,
    entry: Optional[EntryPayload],
    attachments: list[AttachmentRef],
    tenant_id: int,
    user_id: int,
    trace_id: str,
    thread_id: str,
) -> dict:
    """按 agent_type 建业务骨架行并入队；返回 task_started 所需字段。

    返回 { artifact_type, artifact_id, task_id, summary }，直接喂给 dispatch 组装
    task_started 事件。attachment 的 MinIO 引用沿用两阶段上传第一步落库的 object_key。
    """
    if spec.agent_type == "exam":
        return await _start_exam(
            turn_id=turn_id, entry=entry, attachments=attachments, tenant_id=tenant_id,
            user_id=user_id, trace_id=trace_id, thread_id=thread_id,
        )
    if spec.agent_type == "resume":
        return await _start_resume(
            turn_id=turn_id, attachments=attachments, tenant_id=tenant_id,
            user_id=user_id, trace_id=trace_id, thread_id=thread_id,
        )
    raise ValueError(f"非任务型 agent 不能走任务流：{spec.agent_type}")


async def _start_exam(
    *, turn_id, entry, attachments, tenant_id, user_id, trace_id, thread_id
) -> dict:
    exam_id = _entry_value(entry, "exam_id")
    if not exam_id:
        raise ValueError("exam_id 必填（入口字段缺失）")
    object_key = await _object_key_of(attachments)
    if not object_key:
        raise ValueError("exam 必须携带已上传的试卷附件")

    submission_id = str(uuid6.uuid7())
    async with session_scope() as session:
        existing = (
            await session.execute(
                text(
                    "SELECT id FROM agent_exams WHERE id = :exam_id AND tenant_id = :tenant_id"
                ),
                {"exam_id": exam_id, "tenant_id": tenant_id},
            )
        ).fetchone()
        if not existing:
            raise ValueError(f"试卷 ID 不存在（{exam_id}）")
        await session.execute(
            text(
                """
                INSERT INTO agent_exam_submissions
                    (id, tenant_id, exam_id, user_id, turn_id, source, word_minio_path, status,
                     submitted_at, published_at, weak_points, weak_points_summary,
                     create_user_id, update_user_id, create_tenant_id, update_tenant_id)
                VALUES
                    (:id, :tenant_id, :exam_id, :user_id, :turn_id, 'word', :word_path, 'ai_processing',
                     NOW(), NOW(), :weak_points, '', :cu, :uu, :ct, :ut)
                """
            ),
            {
                "id": submission_id,
                "tenant_id": tenant_id,
                "exam_id": exam_id,
                "user_id": user_id,
                "turn_id": turn_id,
                "word_path": object_key,
                "weak_points": json.dumps([]),
                "cu": user_id,
                "uu": user_id,
                "ct": tenant_id,
                "ut": tenant_id,
            },
        )

    await enqueue_task(
        TaskType.EXAM_REVIEW,
        tenant_id=tenant_id,
        user_id=user_id,
        trace_id=trace_id,
        data={
            "submission_id": submission_id,
            "exam_id": exam_id,
            "user_id": user_id,
            "tenant_id": tenant_id,
            "word_minio_path": object_key,
            "turn_id": turn_id,
            "thread_id": thread_id,
            "trace_id": trace_id,
        },
    )
    return {
        "artifact_type": "exam",
        "artifact_id": submission_id,
        "task_id": submission_id,
        "summary": "试卷已提交，AI 正在批改中，完成后等待教师确认。",
    }


async def _start_resume(
    *, turn_id, attachments, tenant_id, user_id, trace_id, thread_id
) -> dict:
    object_key = await _object_key_of(attachments)
    if not object_key:
        raise ValueError("resume 必须携带已上传的简历附件")

    review_id = str(uuid6.uuid7())
    async with session_scope() as session:
        await session.execute(
            text(
                """
                INSERT INTO agent_resume_reviews
                    (id, tenant_id, user_id, turn_id, pdf_minio_path, status,
                     create_user_id, update_user_id, create_tenant_id, update_tenant_id)
                VALUES
                    (:id, :tenant_id, :user_id, :turn_id, :pdf_path, 'processing',
                     :cu, :uu, :ct, :ut)
                """
            ),
            {
                "id": review_id,
                "tenant_id": tenant_id,
                "user_id": user_id,
                "turn_id": turn_id,
                "pdf_path": object_key,
                "cu": user_id,
                "uu": user_id,
                "ct": tenant_id,
                "ut": tenant_id,
            },
        )

    await enqueue_task(
        TaskType.RESUME_REVIEW,
        tenant_id=tenant_id,
        user_id=user_id,
        trace_id=trace_id,
        data={
            "review_id": review_id,
            "user_id": user_id,
            "tenant_id": tenant_id,
            "pdf_minio_path": object_key,
            "turn_id": turn_id,
            "thread_id": thread_id,
            "trace_id": trace_id,
        },
    )
    return {
        "artifact_type": "resume",
        "artifact_id": review_id,
        "task_id": review_id,
        "summary": "简历已接收，正在后台评审...",
    }
