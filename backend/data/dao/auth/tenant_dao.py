"""租户 DAO：租户 CRUD 与「本租户管理员」查询（tenant 表，无审计列，见设计文档 §6）。

- 所有租户地位平等，没有主租户标记，也不存在「全局唯一租户」的约束；
- 租户管理员（tenant_admin）不在此表，而在 agent_user_tenant（按角色名查）；
- 管理员更换的原子事务（原管理员降 student + 写入新 tenant_admin）放在接口层，
  本 DAO 只提供单表读写与「取某租户管理员登录名」的只读查询。
"""
from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import String, bindparam, text

from backend.data.sql import execute_write, fetch_all, fetch_one, fetch_value, session_scope

_COLS = "id, name, enabled"

_GET = text(f"SELECT {_COLS} FROM agent_tenant WHERE id = :tenant_id")
_LIST = text(f"SELECT {_COLS} FROM agent_tenant ORDER BY id")
_INSERT = text(
    "INSERT INTO agent_tenant (name, enabled) VALUES (:name, true) RETURNING id"
)
_GET_BY_NAME = text(f"SELECT {_COLS} FROM agent_tenant WHERE name = :name LIMIT 1")
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
        created_from: Optional[str] = None,
        created_to: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """全部租户（含管理员登录名、用户数、创建/更新时间）；可按创建日期范围过滤。"""
        sql = text(
            """
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
            ORDER BY t.id
            """
        ).bindparams(
            # 显式声明日期参数类型，避免 asyncpg 扩展协议下 Postgres 因
            # "IS NULL 与 ::date 并存" 无法推断参数类型而报
            # "could not determine data type of parameter"（导致 500）
            bindparam("created_from", type_=String),
            bindparam("created_to", type_=String),
        )
        async with session_scope() as session:
            return await fetch_all(
                session, sql, {"created_from": created_from, "created_to": created_to}
            )

    @staticmethod
    async def get_with_stats(tenant_id: int) -> Optional[dict[str, Any]]:
        """按主键取租户详情（含管理员登录名、用户数、创建/更新时间）。"""
        sql = text(
            """
            SELECT t.id, t.name, t.enabled, t.create_at, t.updated_at,
                   (SELECT u.username FROM agent_user_tenant aut
                    JOIN agent_role r ON r.role_id = aut.role_id
                    JOIN "agent_user" u ON u.id = aut.user_id
                    WHERE aut.tenant_id = t.id AND r.name = 'tenant_admin' LIMIT 1
                   ) AS manager_username,
                   (SELECT count(*) FROM agent_user_tenant aut WHERE aut.tenant_id = t.id) AS user_count
            FROM agent_tenant t
            WHERE t.id = :tenant_id
            """
        )
        async with session_scope() as session:
            return await fetch_one(session, sql, {"tenant_id": tenant_id})
