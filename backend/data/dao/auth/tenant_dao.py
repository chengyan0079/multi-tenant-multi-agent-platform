"""租户 DAO：租户 CRUD 与「本租户管理员」查询（tenant 表，无审计列，见设计文档 §6）。

- 主租户标记 is_primary 不绑定具体 id（种子固定为 id=100，但代码一律按 is_primary 判定）；
- 租户管理员（tenant_admin）不在此表，而在 agent_user_tenant（按角色名查）；
- 管理员更换的原子事务（原管理员降 student + 写入新 tenant_admin）放在接口层，
  本 DAO 只提供单表读写与「取某租户管理员登录名」的只读查询。
"""
from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import text

from backend.data.sql import execute_write, fetch_all, fetch_one, fetch_value, session_scope

_COLS = "id, name, enabled, is_primary"

_GET = text(f"SELECT {_COLS} FROM agent_tenant WHERE id = :tenant_id")
_LIST = text(f"SELECT {_COLS} FROM agent_tenant ORDER BY is_primary DESC, id")
_INSERT = text(
    "INSERT INTO agent_tenant (name, enabled, is_primary) "
    "VALUES (:name, true, false) "
    "RETURNING id"
)
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


class TenantDao:
    """租户读写（无审计列）。"""

    @staticmethod
    async def create(name: str) -> int:
        """新建租户（is_primary 恒 false，主租户不可被新建）。"""
        async with session_scope() as session:
            new_id = await fetch_value(session, _INSERT, {"name": name})
            await session.commit()
            return int(new_id)  # type: ignore[return-value]

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
        """全部租户（主租户排前）。"""
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
        created_from: Optional[str] = None,
        created_to: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """全部租户（含管理员登录名、用户数、创建/更新时间），主租户排前；可按创建日期范围过滤。"""
        sql = text(
            """
            SELECT t.id, t.name, t.enabled, t.is_primary, t.create_at, t.updated_at,
                   (SELECT u.username FROM agent_user_tenant aut
                    JOIN agent_role r ON r.role_id = aut.role_id
                    JOIN "agent_user" u ON u.id = aut.user_id
                    WHERE aut.tenant_id = t.id AND r.name = 'tenant_admin' LIMIT 1
                   ) AS manager_username,
                   (SELECT count(*) FROM agent_user_tenant aut WHERE aut.tenant_id = t.id) AS user_count
            FROM agent_tenant t
            WHERE (:created_from IS NULL OR t.create_at::date >= :created_from::date)
              AND (:created_to IS NULL OR t.create_at::date <= :created_to::date)
            ORDER BY t.is_primary DESC, t.id
            """
        )
        async with session_scope() as session:
            return await fetch_all(
                session, sql, {"created_from": created_from, "created_to": created_to}
            )
