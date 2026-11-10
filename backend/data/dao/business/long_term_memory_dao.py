"""长记忆 DAO：agent_long_term_memory，走 text()，按租户+用户+智能体+block 检索。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

from backend.data.sql import fetch_all, fetch_one, session_scope


class LongTermMemoryDao:
    @staticmethod
    async def append(
        *,
        tenant_id: int,
        user_id: int,
        agent_id: str,
        block: str,
        content: str,
        embedding_id: str = "",
    ) -> str:
        """写入一条长记忆，返回新行 id（UUID 字符串）。

        embedding_id 默认为空串：长记忆当前不挂向量，预留给后续语义召回（按用户要求保留该列）。
        """
        async with session_scope() as session:
            row = await fetch_one(
                session,
                text(
                    """INSERT INTO agent_long_term_memory
                       (tenant_id, user_id, agent_id, block, content, embedding_id)
                       VALUES (:tenant_id, :user_id, :agent_id, :block, :content, :embedding_id)
                       RETURNING id"""
                ),
                {
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                    "agent_id": agent_id,
                    "block": block,
                    "content": content,
                    "embedding_id": embedding_id,
                },
            )
            return str(row["id"])

    @staticmethod
    async def list_recent(
        *,
        tenant_id: int,
        user_id: int,
        agent_id: str,
        block: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """按 (租户, 用户, 智能体[, block]) 读取最近 limit 条长记忆。"""
        where = (
            "tenant_id IS NOT DISTINCT FROM :tenant_id "
            "AND user_id IS NOT DISTINCT FROM :user_id "
            "AND agent_id = :agent_id"
        )
        params: dict[str, Any] = {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "agent_id": agent_id,
            "limit": limit,
        }
        if block:
            where += " AND block = :block"
            params["block"] = block
        async with session_scope() as session:
            rows = await fetch_all(
                session,
                text(
                    f"""SELECT id, tenant_id, user_id, agent_id, block, content, embedding_id, create_at
                        FROM agent_long_term_memory
                        WHERE {where}
                        ORDER BY id DESC
                        LIMIT :limit"""
                ),
                params,
            )
            return rows
