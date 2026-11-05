"""会话归属 DAO：agent_thread 的读写，SQL 一律带 tenant_id + user_id。

会话是用户级资源：同租户内两个用户拿到同一个 thread_id 也必须互不可见。
所以这里刻意不提供「只按 id 查」的方法，避免调用方漏掉隔离条件。
"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import text

from backend.data.sql import fetch_value, session_scope

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
