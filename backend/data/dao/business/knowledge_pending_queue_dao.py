"""知识沉淀待审队列数据访问层（agent_knowledge_pending_queue）。

低置信度问答入队，教师复核后补充知识库。状态生命周期：pending -> resolved / dismissed。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

from backend.data.sql import execute_write, fetch_all, fetch_value, session_scope
from backend.data.sql.audit import audit_on_insert, audit_on_update


class KnowledgePendingQueueDao:
    """agent_knowledge_pending_queue 读写。"""

    @staticmethod
    async def insert_pending(
        *,
        tenant_id: int,
        user_id: int,
        question: str,
        confidence: float,
    ) -> None:
        """低置信度问答入队（pending），审计列由审计函数注入提交者。"""
        async with session_scope() as session:
            audit = audit_on_insert(user_id=user_id, tenant_id=tenant_id, with_tenant=True)
            stmt = text(
                """
                INSERT INTO agent_knowledge_pending_queue
                    (tenant_id, question, user_id, confidence, status,
                     create_at, updated_at,
                     create_user_id, update_user_id, create_tenant_id, update_tenant_id)
                VALUES
                    (:tenant_id, :question, :user_id, :confidence, 'pending',
                     now(), now(),
                     :create_user_id, :update_user_id, :create_tenant_id, :update_tenant_id)
                """
            )
            params = {
                "tenant_id": tenant_id,
                "question": question,
                "user_id": user_id,
                "confidence": confidence,
                **audit,
            }
            await execute_write(session, stmt, params)

    @staticmethod
    async def list_pending(
        *,
        tenant_id: int,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """列出某租户 pending 待审条目（创建时间倒序）。"""
        async with session_scope() as session:
            stmt = text(
                """
                SELECT id, tenant_id, user_id, question, confidence, status,
                       resolved_user_id, resolved_at, create_at
                FROM agent_knowledge_pending_queue
                WHERE tenant_id = :tenant_id AND status = 'pending'
                ORDER BY create_at DESC
                LIMIT :limit OFFSET :offset
                """
            )
            return await fetch_all(
                session, stmt, {"tenant_id": tenant_id, "limit": limit, "offset": offset}
            )

    @staticmethod
    async def count_pending(tenant_id: int) -> int:
        async with session_scope() as session:
            stmt = text(
                "SELECT COUNT(*) FROM agent_knowledge_pending_queue "
                "WHERE tenant_id = :tenant_id AND status = 'pending'"
            )
            return int(await fetch_value(session, stmt, {"tenant_id": tenant_id}) or 0)

    @staticmethod
    async def resolve(
        *,
        queue_id: str,
        tenant_id: int,
        resolved_user_id: int,
        status: str,
    ) -> int:
        """教师复核：置 resolved/dismissed，并记录处理人与时间（按租户隔离）。"""
        async with session_scope() as session:
            audit = audit_on_update(user_id=resolved_user_id, tenant_id=tenant_id, with_tenant=True)
            stmt = text(
                """
                UPDATE agent_knowledge_pending_queue
                SET status = :status,
                    resolved_user_id = :resolved_user_id,
                    resolved_at = now(),
                    updated_at = now(),
                    update_user_id = :update_user_id,
                    update_tenant_id = :update_tenant_id
                WHERE id = :queue_id AND tenant_id = :tenant_id
                """
            )
            params = {
                "status": status,
                "resolved_user_id": resolved_user_id,
                "queue_id": queue_id,
                "tenant_id": tenant_id,
                **audit,
            }
            return await execute_write(session, stmt, params)
