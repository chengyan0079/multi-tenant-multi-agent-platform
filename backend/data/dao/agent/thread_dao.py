"""会话归属 DAO：agent_thread 读写，SQL 一律带 tenant_id+user_id，不提供仅按 id 查的方法。"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import text

from backend.data.sql import (
    fetch_all,
    fetch_one,
    fetch_page,
    fetch_value,
    session_scope,
)

# id 由库端 uuid_generate_v4() 生成，RETURNING 直接取回，省一次查询
_INSERT = text("""
INSERT INTO agent_thread (tenant_id, user_id, status)
VALUES (:tenant_id, :user_id, :status)
RETURNING id
""")

# find-or-create：同一 (租户, 用户, 会话键) 命中唯一约束时直接返回已存在 id，
# 避免并发重复建线程。DO UPDATE 仅作占位以触发 RETURNING；
# 关键修复（R1）：冲突时把 id 置为「已存在行自己的 id」（agent_thread.id），
# 而非 EXCLUDED.id（插入行的默认 uuid，冲突行未携带 → 会被改写成新主键），
# 否则同一 session_key 每轮拿到不同 U，统一 checkpoint 失效。
_GET_OR_CREATE = text("""
INSERT INTO agent_thread (tenant_id, user_id, status, session_key)
VALUES (:tenant_id, :user_id, :status, :session_key)
ON CONFLICT ON CONSTRAINT uq_agent_thread_tenant_user_session
DO UPDATE SET id = agent_thread.id
RETURNING id
""")

# 不区分「不存在」与「不属于你」，调用方统一按 404 处理
_SELECT_OWNED = text("""
SELECT 1
FROM agent_thread
WHERE id = CAST(:thread_id AS uuid)
  AND tenant_id = :tenant_id
  AND user_id = :user_id
""")

# 首问后按问题主题更新标题；仅默认标题才覆盖，用户自定义标题不动
_UPDATE_TITLE_IF_DEFAULT = text("""
UPDATE agent_thread
SET title = :title,
    updated_at = date_trunc('second', now())
WHERE id = CAST(:thread_id AS uuid)
  AND tenant_id = :tenant_id
  AND user_id = :user_id
  AND title = '新会话'
""")

# 每条消息成功后刷新最近活跃时间，保证会话列表按 updated_at 排序准确
_TOUCH_QA_SESSION = text("""
UPDATE agent_thread
SET updated_at = date_trunc('second', now())
WHERE id = CAST(:thread_id AS uuid)
  AND tenant_id = :tenant_id
  AND user_id = :user_id
  AND status = 'active'
""")


def _as_uuid(thread_id: str) -> str | None:
    """校验 thread_id 是否为合法 UUID。

    非法值（如客户端随便传的字符串）直接判为「不存在」，否则 DB 比较 uuid = 'xxx'
    会抛类型错误，把 404 变成 500。
    """
    try:
        return str(UUID(thread_id))
    except (TypeError, ValueError, AttributeError):
        return None


class ThreadDao:
    """agent_thread 的归属读写。"""

    @staticmethod
    async def create(*, tenant_id: int, user_id: int) -> str:
        """新建会话（归属当前用户）并返回 id。"""
        async with session_scope() as session:
            thread_id = await fetch_value(
                session,
                _INSERT,
                {"tenant_id": tenant_id, "user_id": user_id, "status": "active"},
            )
            await session.commit()
        return str(thread_id)

    @staticmethod
    async def is_owned(*, thread_id: str, tenant_id: int, user_id: int) -> bool:
        """会话是否属于该用户：租户与用户两个条件同时满足才算。

        不区分「不存在」与「不属于你」，调用方统一按 404 处理，避免探测他人会话。
        """
        tid = _as_uuid(thread_id)
        if tid is None:
            return False
        async with session_scope() as session:
            row = await fetch_value(
                session,
                _SELECT_OWNED,
                {"thread_id": tid, "tenant_id": tenant_id, "user_id": user_id},
            )
        return row is not None

    @staticmethod
    async def get_or_create(
        *, tenant_id: int, user_id: int, session_key: str | None = None
    ) -> str:
        """按 (租户, 用户, 会话键) 查找或创建会话，返回其 id（UUID 字符串，即 U）。

        session_key 用于同用户多会话区分（如 qa 的 session_id）；为 None 时退化为普通新建。
        ON CONFLICT 保证并发安全：重复键直接返回已存在的 id，不会建出两条。
        """
        async with session_scope() as session:
            thread_id = await fetch_value(
                session,
                _GET_OR_CREATE,
                {
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                    "status": "active",
                    "session_key": session_key,
                },
            )
            await session.commit()
        return str(thread_id)

    @staticmethod
    async def touch_qa_session(*, thread_id: str, tenant_id: int, user_id: int) -> int:
        """刷新会话最近活跃时间（每条消息成功后调用）。"""
        tid = _as_uuid(thread_id)
        if tid is None:
            return 0
        async with session_scope() as session:
            result = await session.execute(
                _TOUCH_QA_SESSION,
                {"thread_id": tid, "tenant_id": tenant_id, "user_id": user_id},
            )
            return result.rowcount or 0

    @staticmethod
    async def update_title_if_default(
        *, thread_id: str, tenant_id: int, user_id: int, title: str
    ) -> int:
        """首问后按问题主题更新标题；仅当标题仍为默认「新会话」时更新。"""
        tid = _as_uuid(thread_id)
        if tid is None or not (title or "").strip():
            return 0
        async with session_scope() as session:
            result = await session.execute(
                _UPDATE_TITLE_IF_DEFAULT,
                {
                    "thread_id": tid,
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                    "title": title.strip()[:255],
                },
            )
            return result.rowcount or 0

    @staticmethod
    async def list_sessions(
        *,
        tenant_id: int,
        user_id: int,
        page: int = 1,
        page_size: int = 20,
        status: str | None = None,
    ) -> tuple[list[dict], int]:
        """分页列出当前用户会话（最近活跃降序），附 turn 数与末次 agent_type。"""
        offset = max(page - 1, 0) * page_size
        where = "WHERE t.tenant_id = :ten AND t.user_id = :uid"
        params: dict = {"ten": tenant_id, "uid": user_id, "limit": page_size, "offset": offset}
        if status:
            where += " AND t.status = :status"
            params["status"] = status
        count_sql = text(f"SELECT count(*) FROM agent_thread t {where}")
        list_sql = text(
            "SELECT t.id, t.session_key, t.title, t.status, t.create_at AS created_at, t.updated_at, "
            "(SELECT count(*) FROM agent_unified_turn u WHERE u.thread_id = t.id) AS turn_count, "
            "(SELECT agent_type FROM agent_unified_turn u WHERE u.thread_id = t.id "
            " ORDER BY u.turn_index DESC LIMIT 1) AS last_agent_type "
            f"FROM agent_thread t {where} ORDER BY t.updated_at DESC LIMIT :limit OFFSET :offset"
        )
        async with session_scope() as session:
            total = await fetch_value(session, count_sql, params)
            rows = await fetch_all(session, list_sql, params)
        return [dict(r) for r in rows], int(total or 0)

    @staticmethod
    async def get_session(
        *, tenant_id: int, user_id: int, thread_id: str
    ) -> dict | None:
        """读取单个会话元信息（含 turn 数 / 末次 agent_type）。"""
        tid = _as_uuid(thread_id)
        if tid is None:
            return None
        sql = text(
            "SELECT t.id, t.session_key, t.title, t.status, t.create_at AS created_at, t.updated_at, "
            "(SELECT count(*) FROM agent_unified_turn u WHERE u.thread_id = t.id) AS turn_count, "
            "(SELECT agent_type FROM agent_unified_turn u WHERE u.thread_id = t.id "
            " ORDER BY u.turn_index DESC LIMIT 1) AS last_agent_type "
            "FROM agent_thread t WHERE t.id = :tid AND t.tenant_id = :ten AND t.user_id = :uid"
        )
        async with session_scope() as session:
            rows = await fetch_all(
                session, sql, {"tid": tid, "ten": tenant_id, "uid": user_id}
            )
        return dict(rows[0]) if rows else None

    @staticmethod
    async def delete_session(
        *, tenant_id: int, user_id: int, thread_id: str
    ) -> int:
        """删除会话：**只删 agent_thread**。

        agent_unified_turn / agent_qa_ragas_evals / checkpoints 全部保留：
        - 「咨询结果」页按 turn 查询，不依赖 thread，RAGAS 报告仍可查看；
        - 会话列表按 thread 查询，删除后自然不再出现。
        """
        tid = _as_uuid(thread_id)
        if tid is None:
            return 0
        async with session_scope() as session:
            result = await session.execute(
                text(
                    "DELETE FROM agent_thread WHERE id = :tid "
                    "AND tenant_id = :ten AND user_id = :uid"
                ),
                {"tid": tid, "ten": tenant_id, "uid": user_id},
            )
            await session.commit()
            return result.rowcount or 0

    # ---- 管理端：跨用户（仅按租户），用于会话管理页 ----

    @staticmethod
    @staticmethod
    async def set_title_if_empty(
        *, thread_id: str, tenant_id: int, title: str
    ) -> int:
        """仅当标题为空时写入（天然「只改一次」）。返回受影响行数。"""
        tid = _as_uuid(thread_id)
        if tid is None or not title:
            return 0
        async with session_scope() as session:
            result = await session.execute(
                text(
                    "UPDATE agent_thread SET title = :title, updated_at = now() "
                    "WHERE id = CAST(:tid AS uuid) AND tenant_id = :ten "
                    # 空标题或默认「新会话」都视为未命名，可自动命名一次
                    "AND (title IS NULL OR btrim(title) = '' OR title = '新会话')"
                ),
                {"title": title[:64], "tid": tid, "ten": tenant_id},
            )
            await session.commit()
            return int(result.rowcount or 0)

    async def list_sessions_admin(
        *,
        tenant_id: int,
        user_id: int | None = None,
        page: int = 1,
        page_size: int = 20,
        status: str | None = None,
        thread_id: str | None = None,
        agent_type: str | None = None,
    ) -> tuple[list[dict], int]:
        """管理端分页列出本租户会话（可按 thread_id/状态/agent 过滤）。"""
        offset = max(page - 1, 0) * page_size
        where = "WHERE t.tenant_id = :ten"
        params: dict = {"ten": tenant_id, "limit": page_size, "offset": offset}
        if user_id is not None:
            where += " AND t.user_id = :uid"
            params["uid"] = user_id
        if status:
            where += " AND t.status = :status"
            params["status"] = status
        if thread_id:
            # 支持精确或前缀模糊匹配（UUID 字符串）
            where += " AND CAST(t.id AS text) LIKE :tid_like"
            params["tid_like"] = f"%{thread_id.strip()}%"
        if agent_type:
            where += (
                " AND EXISTS (SELECT 1 FROM agent_unified_turn u2 "
                "WHERE u2.thread_id = t.id AND u2.agent_type = :agt)"
            )
            params["agt"] = agent_type
        count_sql = text(f"SELECT count(*) FROM agent_thread t {where}")
        list_sql = text(
            "SELECT t.id, t.session_key, t.title, t.status, t.create_at AS created_at, t.updated_at, "
            "(SELECT count(*) FROM agent_unified_turn u WHERE u.thread_id = t.id) AS turn_count, "
            "(SELECT agent_type FROM agent_unified_turn u WHERE u.thread_id = t.id "
            " ORDER BY u.turn_index DESC LIMIT 1) AS last_agent_type "
            f"FROM agent_thread t {where} ORDER BY t.updated_at DESC LIMIT :limit OFFSET :offset"
        )
        async with session_scope() as session:
            total = await fetch_value(session, count_sql, params)
            rows = await fetch_all(session, list_sql, params)
        return [dict(r) for r in rows], int(total or 0)

    @staticmethod
    async def get_session_admin(*, tenant_id: int, thread_id: str) -> dict | None:
        """管理端读取单会话元信息（不限 user）。"""
        tid = _as_uuid(thread_id)
        if tid is None:
            return None
        sql = text(
            "SELECT t.id, t.session_key, t.title, t.status, t.create_at AS created_at, t.updated_at, "
            "(SELECT count(*) FROM agent_unified_turn u WHERE u.thread_id = t.id) AS turn_count, "
            "(SELECT agent_type FROM agent_unified_turn u WHERE u.thread_id = t.id "
            " ORDER BY u.turn_index DESC LIMIT 1) AS last_agent_type, "
            # 全会话累计（不受回放 limit 影响）
            "(SELECT coalesce(sum(nullif(u.token_usage->>'total', '')::numeric), 0) "
            " FROM agent_unified_turn u WHERE u.thread_id = t.id) AS total_tokens, "
            "(SELECT coalesce(sum(u.latency_ms), 0) "
            " FROM agent_unified_turn u WHERE u.thread_id = t.id) AS total_latency_ms "
            "FROM agent_thread t WHERE t.id = :tid AND t.tenant_id = :ten"
        )
        async with session_scope() as session:
            rows = await fetch_all(session, sql, {"tid": tid, "ten": tenant_id})
        return dict(rows[0]) if rows else None

    @staticmethod
    async def delete_session_admin(*, tenant_id: int, thread_id: str) -> int:
        """管理端删除会话：**只删 agent_thread**（保留 turn / 评测 / checkpoint）。"""
        tid = _as_uuid(thread_id)
        if tid is None:
            return 0
        async with session_scope() as session:
            result = await session.execute(
                text("DELETE FROM agent_thread WHERE id = :tid AND tenant_id = :ten"),
                {"tid": tid, "ten": tenant_id},
            )
            await session.commit()
            return result.rowcount or 0
