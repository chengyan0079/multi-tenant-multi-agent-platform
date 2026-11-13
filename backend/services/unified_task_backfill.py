"""Broker 任务结果回流：handler 跑完子图后回写一条 task_result 统一会话 turn。"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import text

from backend.common.logger import get_logger, trace_id_ctx
from backend.data.sql import session_scope
from backend.orchestration.unified_schemas import ArtifactRef
from backend.services.unified_conversation import UnifiedConversationService

logger = get_logger("unified_task_backfill")


async def backfill_task_result(
    *,
    agent_type: str,
    artifact_id: str,
    tenant_id: int,
    user_id: int,
    turn_id: Optional[str],
    thread_id: Optional[str],
    trace_id: Optional[str],
) -> None:
    """把异步任务结果写回统一会话。缺少 turn/thread 关联时（旧路径）直接跳过。"""
    if not (turn_id and thread_id):
        return
    # 恢复链路上下文，保证 trace_id 贯穿日志与数据
    token = trace_id_ctx.set(trace_id or "")
    try:
        summary, route_key = await _load_summary(agent_type, artifact_id, tenant_id, user_id)
        svc = UnifiedConversationService()
        from backend.data.dao.agent.unified_turn_dao import UnifiedTurnDao

        turn_index = await UnifiedTurnDao.next_turn_index(
            thread_id=thread_id, tenant_id=tenant_id, user_id=user_id
        )
        artifact = ArtifactRef(
            artifact_type=agent_type, artifact_id=artifact_id, route_key=route_key
        )
        await svc.append_turn(
            thread_id=thread_id,
            tenant_id=tenant_id,
            user_id=user_id,
            agent_type=agent_type,
            spec_version=None,
            trace_id=trace_id,
            turn_index=turn_index,
            event_type="task_result",
            assistant_content=summary,
            payload={
                "artifact_type": agent_type,
                "artifact_id": artifact_id,
                "summary": summary,
                "route_key": route_key,
            },
            routing=None,
            status="success",
            token_usage=None,
        )
        logger.info(
            f"unified_task_backfill.ok agent={agent_type} artifact={artifact_id} thread={thread_id}"
        )
    except Exception:  # noqa: BLE001 - 回流失败不影响主流程，仅记录
        logger.exception(f"unified_task_backfill.failed | agent={agent_type} artifact={artifact_id}")
    finally:
        trace_id_ctx.reset(token)


async def _load_summary(
    agent_type: str, artifact_id: str, tenant_id: int, user_id: int
) -> tuple[str, str]:
    """从业务表取结果摘要与结果页 route_key。"""
    async with session_scope() as session:
        if agent_type == "exam":
            row = (
                (
                    await session.execute(
                        text(
                            "SELECT status, weak_points_summary FROM agent_exam_submissions "
                            "WHERE id = :id AND tenant_id = :ten AND user_id = :uid"
                        ),
                        {"id": artifact_id, "ten": tenant_id, "uid": user_id},
                    )
                )
                .mappings()
                .first()
            )
            summary = (row["weak_points_summary"] or "批改完成") if row else "批改完成"
            return summary, f"exam/submissions/{artifact_id}/review"
        if agent_type == "resume":
            row = (
                (
                    await session.execute(
                        text(
                            "SELECT status, summary FROM agent_resume_reviews "
                            "WHERE id = :id AND tenant_id = :ten AND user_id = :uid"
                        ),
                        {"id": artifact_id, "ten": tenant_id, "uid": user_id},
                    )
                )
                .mappings()
                .first()
            )
            summary = (row["summary"] or "评审完成") if row else "评审完成"
            return summary, f"resume/reviews/{artifact_id}"
    return "任务完成", ""
