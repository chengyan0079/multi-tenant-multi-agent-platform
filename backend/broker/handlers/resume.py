"""简历评审 handler：消费 resume.review 消息，跑 Orchestrator 评审工作流。

幂等与 ack 由消费框架统一负责（见 broker/consumer/strategies.py）：
- 幂等：Outbox 已 done 的消息直接 ack 跳过（at-least-once 重投安全）；
  此处再叠加业务级幂等——评审记录已非 processing 则跳过，避免重复跑图。
- ack：成功返回后框架 mark_done + ack；异常由框架 inc_retry，超限落死信表。
故 handler 只需：鉴权通过 → 幂等校验 → 跑图；失败直接 raise（交给框架重试/死信），
不要自行吞掉异常，也不要在异常时静默标 failed（那会丢失重试机会）。
"""
from __future__ import annotations

from sqlalchemy import text

from backend.app_state import app_state
from backend.broker.envelope import TaskMessage
from backend.broker.security import authorize_task
from backend.common.logger import logger
from backend.data.sql import session_scope


async def _fetch_status(review_id: str) -> str | None:
    """取评审记录当前状态；不存在返回 None。"""
    async with session_scope() as session:
        row = (
            await session.execute(
                text("SELECT status FROM agent_resume_reviews WHERE id = :id"),
                {"id": review_id},
            )
        ).mappings().first()
    return row["status"] if row else None


async def handle_resume_review(msg: TaskMessage) -> None:
    # 零信任：按消息内身份重校验 resume:upload（不凭 topic 假设权限）
    await authorize_task(msg.header.user_id, msg.header.tenant_id, ["resume:upload"])

    data = msg.data
    review_id = data.get("review_id")
    if not review_id:
        logger.warning("[resume.review] 消息缺少 review_id，丢弃")
        return

    # 业务幂等：记录不存在或已非 processing（done/failed）→ 跳过，不重复跑图
    status = await _fetch_status(review_id)
    if status is None:
        logger.warning(f"[resume.review] 评审记录不存在 {review_id}，丢弃")
        return
    if status != "processing":
        logger.info(f"[resume.review] 评审已 {status}，跳过 {review_id}")
        return

    initial_state = {
        "review_id": review_id,
        "user_id": str(data.get("user_id")),
        "tenant_id": str(data.get("tenant_id")),
        "pdf_minio_path": data.get("pdf_minio_path"),
    }

    orch = app_state.orchestrator
    if orch is None:
        # 编排器未就绪属瞬时/启动期问题，raise 让框架重试（后续会就绪）
        raise RuntimeError("编排器未就绪")

    # 跑图：节点内已含 MinIO 下载、LLM 评审、save_results 回写 status='done'。
    # 异常向上抛，由 consumer 重试；重试耗尽则落死信，最终由定时任务标 failed。
    await orch.run_agent("resume", review_id, initial_state)
