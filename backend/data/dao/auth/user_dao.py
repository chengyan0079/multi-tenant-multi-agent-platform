"""用户 DAO：登录认证与账号读写（user 表，密码明文比对）。"""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import Integer, String, bindparam, text

from backend.data.sql import fetch_one, fetch_page, fetch_value, session_scope

_GET_BY_USERNAME = text("""
SELECT id, username, name, password, tenant_id, enabled, create_at, updated_at
FROM "agent_user" WHERE username = :username
""")
_GET = text("""
SELECT id, username, name, password, tenant_id, is_super_admin, enabled, create_at, updated_at
FROM "agent_user" WHERE id = :user_id
""")
_BINDS = (
    # todo asyncpg 扩展协议下 "IS NULL + cast" 无法推断参数类型，必须显式声明
    bindparam("tenant_id", type_=Integer),
    bindparam("username", type_=String),
    bindparam("created_from", type_=String),
    bindparam("created_to", type_=String),
)
_LIST = text("""
SELECT id, username, name, password, tenant_id, is_super_admin, enabled, create_at, updated_at
FROM "agent_user"
WHERE (:tenant_id IS NULL OR tenant_id = :tenant_id)
  AND (:username IS NULL OR username ILIKE '%' || :username || '%')
  AND (:created_from IS NULL OR create_at::date >= CAST(:created_from AS date))
  AND (:created_to IS NULL OR create_at::date <= CAST(:created_to AS date))
ORDER BY id LIMIT :limit OFFSET :offset
""").bindparams(*_BINDS, bindparam("limit", type_=Integer), bindparam("offset", type_=Integer))
_COUNT = text("""
SELECT count(*) FROM "agent_user"
WHERE (:tenant_id IS NULL OR tenant_id = :tenant_id)
  AND (:username IS NULL OR username ILIKE '%' || :username || '%')
  AND (:created_from IS NULL OR create_at::date >= CAST(:created_from AS date))
  AND (:created_to IS NULL OR create_at::date <= CAST(:created_to AS date))
""").bindparams(*_BINDS)
_INSERT = text(
    'INSERT INTO "agent_user" (username, name, password, tenant_id) '
    "VALUES (:username, :name, :password, :tenant_id) "
    "RETURNING id"
)


class UserDao:
    """用户读写：认证与账号管理（user 表无审计列）。"""

    @staticmethod
    async def authenticate(username: str, password: str) -> Optional[dict[str, Any]]:
        """按 username 查 user 表并明文比对密码；账号不存在或密码不匹配返回 None。"""
        row = await UserDao.get_by_username(username)
        if row is None:
            return None
        if row.get("password") != password:
            return None
        if not row.get("enabled"):
            return None
        return row

    @staticmethod
    async def get_by_username(username: str) -> Optional[dict[str, Any]]:
        """按登录名取用户（含 password，调用方不得在响应里外泄）。"""
        async with session_scope() as session:
            return await fetch_one(session, _GET_BY_USERNAME, {"username": username})

    @staticmethod
    async def get(user_id: int) -> Optional[dict[str, Any]]:
        """按主键取用户（含 tenant_id，供 home_tenant_id 审计归属）。"""
        async with session_scope() as session:
            return await fetch_one(session, _GET, {"user_id": user_id})

    @staticmethod
    async def list_users(
        tenant_id: Optional[int] = None,
        username: Optional[str] = None,
        created_from: Optional[str] = None,
        created_to: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        params = {
            "tenant_id": tenant_id,
            "username": username,
            "created_from": created_from,
            "created_to": created_to,
        }
        async with session_scope() as session:
            return await fetch_page(session, _LIST, _COUNT, params, page=page, page_size=page_size)

    @staticmethod
    async def create(*, username: str, name: str, password: str, tenant_id: int) -> int:
        """新建账号（密码一次性设定），返回新主键 id。user 表无审计列。"""
        async with session_scope() as session:
            new_id = await fetch_value(
                session,
                _INSERT,
                {
                    "username": username,
                    "name": name,
                    "password": password,
                    "tenant_id": tenant_id,
                },
            )
            await session.commit()
            return int(new_id)  # type: ignore[return-value]
