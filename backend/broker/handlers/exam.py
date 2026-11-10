"""试卷批改 handler：消费 exam.review，跑 Orchestrator 批改工作流，到 HITL 暂停后 ack。"""

from __future__ import annotations

from sqlalchemy import text

from backend.app_state import app_state
from backend.broker.envelope import TaskMessage
from backend.broker.security import authorize_task
from backend.common.logger import logger
from backend.data.sql import session_scope
from backend.security.rbac import Scope


async def _fetch_status(submission_id: str) -> str | None:
    """取提交记录当前状态；不存在返回 None。"""
    async with session_scope() as session:
        row = (
            (
                await session.execute(
                    text("SELECT status FROM agent_exam_submissions WHERE id = :id"),
                    {"id": submission_id},
                )
            )
            .mappings()
            .first()
        )
    return row["status"] if row else None


async def handle_exam_review(msg: TaskMessage) -> None:
    # 零信任：按消息内身份重校验 exam:add（不凭 topic 假设权限）
    await authorize_task(msg.header.user_id, msg.header.tenant_id, [Scope.EXAM_UPLOAD])

    data = msg.data
    submission_id = data.get("submission_id")
    if not submission_id:
        logger.warning("[exam.review] 消息缺少 submission_id，丢弃")
        return

    # 业务幂等：记录不存在或已非 ai_processing（done/pending_review 等）→ 跳过
    status = await _fetch_status(submission_id)
    if status is None:
        logger.warning(f"[exam.review] 提交记录不存在 {submission_id}，丢弃")
        return
    if status != "ai_processing":
        logger.info(f"[exam.review] 提交已 {status}，跳过 {submission_id}")
        return

    initial_state = {
        "word_minio_path": data.get("word_minio_path"),
        "exam_id": data.get("exam_id"),
        "submission_id": submission_id,
        "student_id": str(data.get("user_id")),
        "tenant_id": str(data.get("tenant_id")),
        "user_id": str(data.get("user_id")),
        "session_id": submission_id,
    }

    orch = app_state.orchestrator
    if orch is None:
        # 编排器未就绪属瞬时/启动期问题，raise 让框架重试
        raise RuntimeError("编排器未就绪")

    # 跑图：parse → 三轨 → 汇总 → 薄弱点 → notify → teacher_review 暂停（状态落 checkpointer）
    await orch.run_agent("exam", submission_id, initial_state)

    # 文件已持久化于 MinIO（key 在 state.word_minio_path），无需清理本地临时文件
