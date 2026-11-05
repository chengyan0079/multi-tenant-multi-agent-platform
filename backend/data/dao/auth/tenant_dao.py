"""租户 DAO：租户 CRUD 与「本租户管理员」查询（tenant 表，无审计列）。"""
from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import Integer, String, bindparam, text

from backend.data.sql import execute_write, fetch_all, fetch_one, fetch_page, fetch_value, session_scope

_GET = text("SELECT id, name, enabled FROM agent_tenant WHERE id = :tenant_id")
_LIST = text("SELECT id, name, enabled FROM agent_tenant ORDER BY id")
_INSERT = text(
    "INSERT INTO agent_tenant (name, enabled) VALUES (:name, true) RETURNING id"
)
_GET_BY_NAME = text("SELECT id, name, enabled FROM agent_tenant WHERE name = :name LIMIT 1")
# 只允许改名/启停：租户没有任何身份标记列可在更新时改动，超管身份只认 agent_user.is_super_admin
_UPDATE = text(
    "UPDATE agent_tenant SET name = COALESCE(:name, name), "
    "enabled = COALESCE(:enabled, enabled) WHERE id = :tenant_id"
)
_GET_MANAGER = text(
    "SELECT u.username FROM agent_user_tenant aut "
    "JOIN agent_role r ON r.role_id = aut.role_id "
    'JOIN "agent_user" u ON u.id = aut.user_id '
    "WHERE aut.tenant_id = :tenant_id AND r.name = 'tenant_admin' "
    "LIMIT 1"
)
# 表间无外键，删除租户需手动级联：先清成员关系，再删归属用户，最后删租户
_DELETE_MEMBERSHIPS = text("DELETE FROM agent_user_tenant WHERE tenant_id = :tenant_id")
_DELETE_USERS = text('DELETE FROM "agent_user" WHERE tenant_id = :tenant_id')
_DELETE_TENANT = text("DELETE FROM agent_tenant WHERE id = :tenant_id")
# 租户停用/删除时级联禁用其下用户（无外键，手动维护）
_SET_USERS_ENABLED = text('UPDATE "agent_user" SET enabled = :enabled WHERE tenant_id = :tenant_id')

_STATS_BINDS = (
    # todo asyncpg 扩展协议下 "IS NULL + cast" 无法推断参数类型，需显式声明
    bindparam("created_from", type_=String),
    bindparam("created_to", type_=String),
    bindparam("name", type_=String),
)
_LIST_STATS = text("""
SELECT t.id, t.name, t.enabled, t.create_at, t.updated_at,
    (SELECT u.username FROM agent_user_tenant aut
     JOIN agent_role r ON r.role_id = aut.role_id
     JOIN "agent_user" u ON u.id = aut.user_id
     WHERE aut.tenant_id = t.id AND r.name = 'tenant_admin' LIMIT 1
    ) AS manager_username,
    (SELECT count(*) FROM agent_user_tenant aut WHERE aut.tenant_id = t.id) AS user_count
FROM agent_tenant t
WHERE (:created_from IS NULL OR t.create_at::date >= CAST(:created_from AS date))
  AND (:created_to IS NULL OR t.create_at::date <= CAST(:created_to AS date))
  AND (:name IS NULL OR t.name ILIKE '%' || :name || '%')
ORDER BY t.id LIMIT :limit OFFSET :offset
""").bindparams(
    *_STATS_BINDS,
    bindparam("limit", type_=Integer),
    bindparam("offset", type_=Integer),
)
_COUNT_STATS = text("""
SELECT count(*) FROM agent_tenant t
WHERE (:created_from IS NULL OR t.create_at::date >= CAST(:created_from AS date))
  AND (:created_to IS NULL OR t.create_at::date <= CAST(:created_to AS date))
  AND (:name IS NULL OR t.name ILIKE '%' || :name || '%')
""").bindparams(*_STATS_BINDS)
_GET_STATS = text("""
SELECT t.id, t.name, t.enabled, t.create_at, t.updated_at,
    (SELECT u.username FROM agent_user_tenant aut
     JOIN agent_role r ON r.role_id = aut.role_id
     JOIN "agent_user" u ON u.id = aut.user_id
     WHERE aut.tenant_id = t.id AND r.name = 'tenant_admin' LIMIT 1
    ) AS manager_username,
    (SELECT count(*) FROM agent_user_tenant aut WHERE aut.tenant_id = t.id) AS user_count
FROM agent_tenant t WHERE t.id = :tenant_id
""")


class TenantDao:
    """租户读写（无审计列）。"""

    @staticmethod
    async def create(name: str) -> int:
        """新建租户，只落名称与启用状态。"""
        async with session_scope() as session:
            new_id = await fetch_value(session, _INSERT, {"name": name})
            await session.commit()
            return int(new_id)  # type: ignore[return-value]

    @staticmethod
    async def get_by_name(name: str) -> Optional[dict[str, Any]]:
        """按名称精确查租户（表上无唯一约束，重名由接口层拦）。"""
        async with session_scope() as session:
            return await fetch_one(session, _GET_BY_NAME, {"name": name})

    @staticmethod
    async def update(
        tenant_id: int,
        *,
        name: Optional[str] = None,
        enabled: Optional[bool] = None,
    ) -> int:
        """改名 / 启停（NULL 表示不改动该列）。"""
        async with session_scope() as session:
            return await execute_write(
                session,
                _UPDATE,
                {"tenant_id": tenant_id, "name": name, "enabled": enabled},
            )

    @staticmethod
    async def get(tenant_id: int) -> Optional[dict[str, Any]]:
        async with session_scope() as session:
            return await fetch_one(session, _GET, {"tenant_id": tenant_id})

    @staticmethod
    async def list_tenants() -> list[dict[str, Any]]:
        """全部租户。"""
        async with session_scope() as session:
            return await fetch_all(session, _LIST)

    @staticmethod
    async def get_manager_username(tenant_id: int) -> Optional[str]:
        """取某租户当前管理员登录名（tenant_admin 角色），无则返回 None。"""
        async with session_scope() as session:
            row = await fetch_one(session, _GET_MANAGER, {"tenant_id": tenant_id})
        return row["username"] if row else None

    @staticmethod
    async def list_with_stats(
        name: Optional[str] = None,
        created_from: Optional[str] = None,
        created_to: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        params = {"name": name, "created_from": created_from, "created_to": created_to}
        async with session_scope() as session:
            return await fetch_page(
                session, _LIST_STATS, _COUNT_STATS, params,
                page=page, page_size=page_size,
            )

    @staticmethod
    async def get_with_stats(tenant_id: int) -> Optional[dict[str, Any]]:
        async with session_scope() as session:
            return await fetch_one(session, _GET_STATS, {"tenant_id": tenant_id})

    @staticmethod
    async def delete(tenant_id: int) -> dict[str, int]:
        """删除租户，并级联清理本租户成员关系与归属用户（同一事务，自动提交）。"""
        async with session_scope() as session:
            memberships = await execute_write(
                session, _DELETE_MEMBERSHIPS, {"tenant_id": tenant_id}
            )
            users = await execute_write(session, _DELETE_USERS, {"tenant_id": tenant_id})
            deleted = await execute_write(session, _DELETE_TENANT, {"tenant_id": tenant_id})
            return {
                "deleted": deleted,
                "deleted_users": users,
                "deleted_memberships": memberships,
            }

    @staticmethod
    async def set_users_enabled(tenant_id: int, enabled: bool) -> int:
        """批量设置本租户用户启用状态（租户停用时级联禁用）。"""
        async with session_scope() as session:
            return await execute_write(
                session,
                _SET_USERS_ENABLED,
                {"tenant_id": tenant_id, "enabled": enabled},
            )
