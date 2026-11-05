"""Outbox 读写（agent_outbox）：投递协程与消费端共用。"""
from __future__ import annotations

import json
from typing import Optional

from sqlalchemy import text

from backend.data.sql import execute_write, fetch_all, fetch_one, fetch_page, session_scope

_ENQUEUE = text(
    # id 由应用生成（即消息 key），便于全链路用同一个幂等键；
    # retry_count 显式给 0：建表脚本里该列 NOT NULL 且无默认值，依赖库默认会插入失败
    "INSERT INTO agent_outbox (id, topic, payload, tenant_id, status, retry_count) "
    "VALUES (:id, :topic, :payload, :tenant_id, 'pending', 0) RETURNING id"
)
_MARK_SENT = text(
    "UPDATE agent_outbox SET status='sent', sent_at=now(), retry_count=:retry_count "
    "WHERE id=:id AND status<>'failed'"
)
_MARK_DONE = text(
    "UPDATE agent_outbox SET status='done', retry_count=:retry_count WHERE id=:id"
)
_MARK_FAILED = text(
    "UPDATE agent_outbox SET status='failed', last_error=:error, retry_count=:retry_count "
    "WHERE id=:id"
)
_INC_RETRY = text(
    "UPDATE agent_outbox SET retry_count = retry_count + 1, last_error=:error "
    "WHERE id=:id RETURNING retry_count"
)
_FETCH_PENDING = text(
    "SELECT id, topic, payload, tenant_id, retry_count FROM agent_outbox "
    "WHERE status='pending' ORDER BY create_at ASC LIMIT :limit"
)


class OutboxDao:
    """本地消息表读写。"""

    @staticmethod
    async def enqueue(
        *, message_id: str, topic: str, payload: dict, tenant_id: Optional[int]
    ) -> str:
        """写入一条待投递消息，返回 id（与传入的 message_id 一致）。"""
        async with session_scope() as session:
            row = await fetch_one(
                session,
                _ENQUEUE,
                # JSONB 列接受 JSON 文本；读回时 asyncpg 自动解析为 dict
                {
                    "id": message_id,
                    "topic": topic,
                    "payload": json.dumps(payload),
                    "tenant_id": tenant_id,
                },
            )
            await session.commit()
            return row["id"]

    @staticmethod
    async def mark_sent(id: str, retry_count: int = 0) -> None:
        async with session_scope() as session:
            await execute_write(session, _MARK_SENT, {"id": id, "retry_count": retry_count})
            await session.commit()

    @staticmethod
    async def mark_done(id: str, retry_count: int = 0) -> None:
        async with session_scope() as session:
            await execute_write(session, _MARK_DONE, {"id": id, "retry_count": retry_count})
            await session.commit()

    @staticmethod
    async def mark_failed(id: str, error: str, retry_count: int = 0) -> None:
        async with session_scope() as session:
            await execute_write(
                session, _MARK_FAILED, {"id": id, "error": error, "retry_count": retry_count}
            )
            await session.commit()

    @staticmethod
    async def inc_retry(id: str, error: str) -> int:
        """失败计数 +1，返回最新重试次数。无记录返回 0。"""
        async with session_scope() as session:
            row = await fetch_one(session, _INC_RETRY, {"id": id, "error": error})
            await session.commit()
            return row["retry_count"] if row else 0

    @staticmethod
    async def fetch_pending(limit: int = 50) -> list[dict]:
        """取出待投递消息（按时间升序），供投递协程扫描。"""
        async with session_scope() as session:
            return await fetch_all(session, _FETCH_PENDING, {"limit": limit})

    @staticmethod
    async def fetch_status(id: str) -> Optional[str]:
        """查单条状态（幂等判定用）；无记录返回 None。"""
        async with session_scope() as session:
            row = await fetch_one(
                session, text("SELECT status FROM agent_outbox WHERE id=:id"), {"id": id}
            )
            return row["status"] if row else None

    @staticmethod
    async def get(id: str) -> Optional[dict]:
        """查单条完整记录（含 tenant_id，状态变更前做归属校验）。"""
        async with session_scope() as session:
            return await fetch_one(
                session,
                text("SELECT id, tenant_id, status FROM agent_outbox WHERE id=:id"),
                {"id": id},
            )

    @staticmethod
    async def get_detail(id: str) -> Optional[dict]:
        """查单条完整记录（含 payload），供详情展示。"""
        async with session_scope() as session:
            return await fetch_one(
                session,
                text(
                    "SELECT id, topic, payload, tenant_id, status, retry_count, "
                    "last_error, sent_at, create_at, updated_at FROM agent_outbox WHERE id=:id"
                ),
                {"id": id},
            )

    @staticmethod
    async def list_outbox(
        page: int,
        page_size: int,
        status: str | None = None,
        tenant_id: int | None = None,
    ) -> tuple[list[dict], int]:
        conds: list[str] = []
        params: dict = {}
        if status is not None:
            conds.append("status = :status")
            params["status"] = status
        if tenant_id is not None:
            conds.append("tenant_id = :tenant_id")
            params["tenant_id"] = tenant_id
        where = ("WHERE " + " AND ".join(conds)) if conds else ""
        list_sql = text(
            f"SELECT id, topic, status, retry_count, last_error, tenant_id, "
            f"sent_at, create_at, updated_at FROM agent_outbox {where} "
            "ORDER BY create_at DESC LIMIT :limit OFFSET :offset"
        )
        count_sql = text(f"SELECT count(*) FROM agent_outbox {where}")
        async with session_scope() as session:
            return await fetch_page(
                session, list_sql, count_sql, params, page=page, page_size=page_size
            )

    @staticmethod
    async def update_status(
        id: str, status: str, expect_tenant_id: int | None = None
    ) -> int:
        """变更状态（重投=pending / 标记完成=done / 失败=failed）；可限定归属租户。"""
        sql = "UPDATE agent_outbox SET status=:status, last_error=NULL WHERE id=:id"
        params: dict = {"id": id, "status": status}
        if expect_tenant_id is not None:
            sql += " AND tenant_id=:tenant_id"
            params["tenant_id"] = expect_tenant_id
        async with session_scope() as session:
            n = await execute_write(session, text(sql), params)
            await session.commit()
            return int(n)


class DeadLetterDao:
    """死信落库（agent_dead_letter）：消费重试超限的任务，便于排查与告警。"""

    _INSERT = text(
        "INSERT INTO agent_dead_letter (topic, payload, origin_queue, error, retry_count, tenant_id) "
        "VALUES (:topic, :payload, :origin_queue, :error, :retry_count, :tenant_id)"
    )

    @staticmethod
    async def write(
        *,
        topic: str,
        payload: bytes,
        origin_queue: str | None,
        error: str,
        retry_count: int,
        tenant_id: Optional[int],
    ) -> None:
        async with session_scope() as session:
            await execute_write(
                session,
                DeadLetterDao._INSERT,
                {
                    "topic": topic,
                    "payload": payload.decode("utf-8"),
                    "origin_queue": origin_queue,
                    "error": error,
                    "retry_count": retry_count,
                    "tenant_id": tenant_id,
                },
            )
            await session.commit()

    @staticmethod
    async def list_dead_letters(
        page: int,
        page_size: int,
        tenant_id: int | None = None,
    ) -> tuple[list[dict], int]:
        conds: list[str] = []
        params: dict = {}
        if tenant_id is not None:
            conds.append("tenant_id = :tenant_id")
            params["tenant_id"] = tenant_id
        where = ("WHERE " + " AND ".join(conds)) if conds else ""
        list_sql = text(
            f"SELECT id, topic, payload, origin_queue, error, retry_count, "
            f"tenant_id, create_at FROM agent_dead_letter {where} "
            "ORDER BY create_at DESC LIMIT :limit OFFSET :offset"
        )
        count_sql = text(f"SELECT count(*) FROM agent_dead_letter {where}")
        async with session_scope() as session:
            return await fetch_page(
                session, list_sql, count_sql, params, page=page, page_size=page_size
            )

    @staticmethod
    async def get(id: str) -> Optional[dict]:
        """查单条死信完整记录（含 payload），供详情展示。"""
        async with session_scope() as session:
            return await fetch_one(
                session,
                text(
                    "SELECT id, topic, payload, origin_queue, error, retry_count, "
                    "tenant_id, create_at FROM agent_dead_letter WHERE id=:id"
                ),
                {"id": id},
            )
