"""会话归属 DAO：agent_thread 的读写，SQL 一律带 tenant_id + user_id。

会话是用户级资源：同租户内两个用户拿到同一个 thread_id 也必须互不可见。
所以这里刻意不提供「只按 id 查」的方法，避免调用方漏掉隔离条件。
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import text

from backend.data.sql import fetch_one, fetch_page, fetch_value, session_scope

# id 由库端 uuid_generate_v4() 生成，RETURNING 直接取回，省一次查询
_INSERT = text("""
INSERT INTO agent_thread (tenant_id, user_id, status, graph_name)
VALUES (:tenant_id, :user_id, :status, :graph_name)
RETURNING id
""")

# find-or-create：同一 (租户, 用户, 图, 会话键) 命中唯一约束时直接返回已存在 id，
# 避免并发重复建线程。DO UPDATE 仅作占位以触发 RETURNING（幂等更新 id=id）。
_GET_OR_CREATE = text("""
INSERT INTO agent_thread (tenant_id, user_id, status, graph_name, session_key)
VALUES (:tenant_id, :user_id, :status, :graph_name, :session_key)
ON CONFLICT ON CONSTRAINT uq_agent_thread_tenant_user_graph_session
DO UPDATE SET id = EXCLUDED.id
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

_LIST_QA_SESSIONS = text("""
SELECT th.id, th.tenant_id, th.user_id, th.status, th.graph_name, th.session_key,
       th.title, th.create_at, th.updated_at
FROM agent_thread th
WHERE th.tenant_id = :tenant_id AND th.user_id = :user_id
  AND th.graph_name = 'qa' AND th.status = 'active'
ORDER BY th.updated_at DESC
LIMIT :limit OFFSET :offset
""")

_COUNT_QA_SESSIONS = text("""
SELECT count(*) FROM agent_thread th
WHERE th.tenant_id = :tenant_id AND th.user_id = :user_id
  AND th.graph_name = 'qa' AND th.status = 'active'
""")

_SELECT_QA_SESSION = text("""
SELECT th.id, th.tenant_id, th.user_id, th.status, th.graph_name, th.session_key,
       th.title, th.create_at, th.updated_at
FROM agent_thread th
WHERE th.id = CAST(:thread_id AS uuid) AND th.tenant_id = :tenant_id
  AND th.user_id = :user_id AND th.status = 'active'
""")

_INSERT_QA_SESSION = text("""
INSERT INTO agent_thread (tenant_id, user_id, status, graph_name, session_key, title)
VALUES (:tenant_id, :user_id, 'active', 'qa', :session_key, :title)
RETURNING id
""")

# 软删：会话归档而非物理删除，checkpointer 保留可恢复
_ARCHIVE_QA_SESSION = text("""
UPDATE agent_thread
SET status = 'archived'
WHERE id = CAST(:thread_id AS uuid)
  AND tenant_id = :tenant_id
  AND user_id = :user_id
  AND status = 'active'
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
    async def create(*, tenant_id: int, user_id: int, graph_name: str = "") -> str:
        """新建会话（归属当前用户）并返回 id。"""
        async with session_scope() as session:
            thread_id = await fetch_value(
                session,
                _INSERT,
                {
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                    "status": "active",
                    "graph_name": graph_name,
                },
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
        *, tenant_id: int, user_id: int, graph_name: str = "", session_key: str | None = None
    ) -> str:
        """按 (租户, 用户, 图, 会话键) 查找或创建会话，返回其 id（UUID 字符串）。

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
                    "graph_name": graph_name,
                    "session_key": session_key,
                },
            )
            await session.commit()
        return str(thread_id)

    @staticmethod
    async def list_qa_sessions(
        *, tenant_id: int, user_id: int, page: int, page_size: int
    ) -> tuple[list[dict[str, Any]], int]:
        """当前用户在某租户下的问答会话分页。"""
        async with session_scope() as session:
            return await fetch_page(
                session,
                _LIST_QA_SESSIONS,
                _COUNT_QA_SESSIONS,
                {"tenant_id": tenant_id, "user_id": user_id},
                page=page,
                page_size=page_size,
            )

    @staticmethod
    async def create_qa_session(
        *, tenant_id: int, user_id: int, session_key: str, title: str = "新会话"
    ) -> str:
        """新建问答会话（thread.session_key 即会话标识，title 为展示标题）。"""
        async with session_scope() as session:
            thread_id = await fetch_value(
                session,
                _INSERT_QA_SESSION,
                {
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                    "session_key": session_key,
                    "title": title or "新会话",
                },
            )
        return str(thread_id)

    @staticmethod
    async def get_qa_session(
        *, thread_id: str, tenant_id: int, user_id: int
    ) -> dict[str, Any] | None:
        """取单个未归档会话（含标题）。"""
        tid = _as_uuid(thread_id)
        if tid is None:
            return None
        async with session_scope() as session:
            return await fetch_one(
                session,
                _SELECT_QA_SESSION,
                {"thread_id": tid, "tenant_id": tenant_id, "user_id": user_id},
            )

    @staticmethod
    async def archive_qa_session(*, thread_id: str, tenant_id: int, user_id: int) -> int:
        """软删会话（status='archived'），checkpointer 保留可恢复，返回受影响行数。"""
        tid = _as_uuid(thread_id)
        if tid is None:
            return 0
        async with session_scope() as session:
            result = await session.execute(
                _ARCHIVE_QA_SESSION,
                {"thread_id": tid, "tenant_id": tenant_id, "user_id": user_id},
            )
            return result.rowcount or 0

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
