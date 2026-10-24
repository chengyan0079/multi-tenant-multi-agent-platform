"""RBAC DAO：角色目录、角色权限、用户-租户-角色分配、租户开关。

四张表的审计列不一样，写之前先看清：
- `agent_role`：只有 user 审计列（全局表）；
- `agent_role_permission` / `agent_user_tenant`：多对多中间表，**无审计列**；
- `tenant`：只有业务列，没有审计列。
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import text

from backend.data.sql import execute_write, fetch_one, session_scope
from backend.data.sql.audit import audit_on_insert

_INSERT_ROLE = text("""
INSERT INTO agent_role (role_id, name, description, create_user_id, update_user_id)
VALUES (:role_id, :name, :description, :create_user_id, :update_user_id)
ON CONFLICT (role_id) DO NOTHING
""")

_INSERT_PERMISSION = text("""
INSERT INTO agent_role_permission (role_id, scope)
VALUES (:role_id, :scope)
ON CONFLICT (role_id, scope) DO NOTHING
""")

# 一次 join 拿全身份快照：分配不存在 / 角色不存在 / 租户停用 都退化成「无行」
_GET_IDENTITY = text("""
SELECT r.name AS role_name,
       t.is_primary AS tenant_is_primary,
       COALESCE(array_agg(p.scope) FILTER (WHERE p.scope IS NOT NULL), '{}'::text[]) AS scopes
FROM agent_user_tenant aut
JOIN agent_role r ON r.role_id = aut.role_id
JOIN tenant t ON t.id = aut.tenant_id
LEFT JOIN agent_role_permission p ON p.role_id = aut.role_id
WHERE aut.user_id = :user_id
  AND aut.tenant_id = :tenant_id
  AND t.enabled
GROUP BY r.name, t.is_primary
""")

# created_at 在 DDL 里没有 DEFAULT，必须显式给值
_UPSERT_MEMBERSHIP = text("""
INSERT INTO agent_user_tenant (user_id, tenant_id, role_id, created_at)
VALUES (:user_id, :tenant_id, :role_id, now())
ON CONFLICT (user_id, tenant_id) DO UPDATE SET role_id = EXCLUDED.role_id
""")


class RbacDao:
    """角色、权限点、用户租户分配的读写。"""

    @staticmethod
    async def ensure_roles_and_permissions(
        roles: list[tuple[int, str, str]],
        permissions: list[tuple[int, str]],
        *,
        user_id: int | None = None,
    ) -> tuple[int, int]:
        """幂等写入内置角色与权限点（单事务），返回 (新增角色数, 新增权限数)。

        `roles` 为 (role_id, name, description)，`permissions` 为 (role_id, scope)。
        启动期没有请求上下文，调用方须显式传 user_id=SYSTEM_USER_ID。
        """
        audit = audit_on_insert(user_id=user_id, with_tenant=False)
        async with session_scope() as session:
            created_roles = 0
            for role_id, name, description in roles:
                created_roles += await execute_write(
                    session,
                    _INSERT_ROLE,
                    {
                        "role_id": role_id,
                        "name": name,
                        "description": description,
                        **audit,
                    },
                )
            created_perms = 0
            for role_id, scope in permissions:
                created_perms += await execute_write(
                    session, _INSERT_PERMISSION, {"role_id": role_id, "scope": scope}
                )
            await session.commit()
        return created_roles, created_perms

    @staticmethod
    async def get_identity(user_id: int, tenant_id: int) -> dict[str, Any] | None:
        """取用户在某租户的身份快照（角色名、是否主租户、权限点）。

        分配不存在、角色缺失、租户不存在或已停用，统一返回 None。
        """
        async with session_scope() as session:
            row = await fetch_one(
                session, _GET_IDENTITY, {"user_id": user_id, "tenant_id": tenant_id}
            )
        if row is None:
            return None
        # array_agg 在不同驱动下可能返回 list 或 '{a,b}' 文本，统一成 list
        scopes = row.get("scopes")
        if isinstance(scopes, str):
            scopes = [s for s in scopes.strip("{}").split(",") if s]
        row["scopes"] = list(scopes or [])
        return row

    @staticmethod
    async def upsert_membership(user_id: int, tenant_id: int, role_id: int) -> None:
        """分配/更新角色（PK=(user_id, tenant_id) 冲突即更新）。"""
        async with session_scope() as session:
            await execute_write(
                session,
                _UPSERT_MEMBERSHIP,
                {"user_id": user_id, "tenant_id": tenant_id, "role_id": role_id},
            )
            await session.commit()
