"""RBAC DAO：角色目录、角色权限、用户-租户-角色分配。"""

# 各表审计列不一致：agent_role 仅 user 列，中间表无审计列，写 SQL 前先核对列定义。
from __future__ import annotations

from typing import Any

from sqlalchemy import Integer, String, bindparam, text

from backend.data.sql import (
    execute_write,
    fetch_all,
    fetch_one,
    fetch_page,
    fetch_value,
    session_scope,
)
from backend.data.sql.audit import audit_on_insert
from backend.observability.exception import BizException, ErrCode

_INSERT_ROLE = text("""
INSERT INTO agent_role (role_id, name, description, create_user_id, update_user_id)
VALUES (:role_id, :name, :description, :create_user_id, :update_user_id)
ON CONFLICT (role_id) DO NOTHING
""")

_UPDATE_ROLE = text("""
UPDATE agent_role
SET name = :name,
    description = :description,
    update_user_id = :update_user_id,
    updated_at = now()
WHERE role_id = :role_id
""")

_INSERT_PERMISSION = text("""
INSERT INTO agent_role_permission (role_id, scope)
VALUES (:role_id, :scope)
ON CONFLICT (role_id, scope) DO NOTHING
""")

# 一次 join 拿全身份快照：分配不存在 / 角色不存在 / 租户停用 都退化成「无行」
_GET_IDENTITY = text("""
SELECT r.name AS role_name,
       COALESCE(array_agg(p.scope) FILTER (WHERE p.scope IS NOT NULL), '{}'::text[]) AS scopes
FROM agent_user_tenant aut
JOIN agent_role r ON r.role_id = aut.role_id
JOIN agent_tenant t ON t.id = aut.tenant_id
LEFT JOIN agent_role_permission p ON p.role_id = aut.role_id
WHERE aut.user_id = :user_id
  AND aut.tenant_id = :tenant_id
  AND t.enabled
GROUP BY r.name
""")

# created_at 在 DDL 里没有 DEFAULT，必须显式给值
_UPSERT_MEMBERSHIP = text("""
INSERT INTO agent_user_tenant (user_id, tenant_id, role_id, created_at)
VALUES (:user_id, :tenant_id, :role_id, now())
ON CONFLICT (user_id, tenant_id) DO UPDATE SET role_id = EXCLUDED.role_id
""")

# 超管分支：身份只认 agent_user.is_super_admin 标记，与租户表无关；
# scopes 取 admin 角色权限点，超管本身不挂任何租户。
_GET_SUPER_ADMIN = text("""
SELECT
  COALESCE(array_agg(p.scope) FILTER (WHERE p.scope IS NOT NULL), '{}'::text[]) AS scopes
FROM agent_user u
CROSS JOIN agent_role r
LEFT JOIN agent_role_permission p ON p.role_id = r.role_id
WHERE u.id = :user_id AND u.is_super_admin AND r.name = 'admin'
GROUP BY u.id
""")

# 登录选租户：列出用户在各个租户（含停用）的分配
_GET_USER_ASSIGNMENTS = text("""
SELECT aut.tenant_id AS tenant_id, t.name AS tenant_name,
       t.enabled AS tenant_enabled,
       r.name AS role_name,
       COALESCE(array_agg(p.scope) FILTER (WHERE p.scope IS NOT NULL), '{}'::text[]) AS scopes
FROM agent_user_tenant aut
JOIN agent_tenant t ON t.id = aut.tenant_id
JOIN agent_role r ON r.role_id = aut.role_id
LEFT JOIN agent_role_permission p ON p.role_id = aut.role_id
WHERE aut.user_id = :user_id
GROUP BY aut.tenant_id, t.name, t.enabled, r.name
ORDER BY aut.tenant_id
""")

# 角色目录 + 权限点（GET /admin/roles）
_ROLES_SELECT = """
SELECT r.role_id, r.name, r.description,
       COALESCE(array_agg(p.scope) FILTER (WHERE p.scope IS NOT NULL), '{}'::text[]) AS scopes
FROM agent_role r
LEFT JOIN agent_role_permission p ON p.role_id = r.role_id
GROUP BY r.role_id, r.name, r.description
"""
_LIST_ROLES_PERMS = text(_ROLES_SELECT + "ORDER BY r.role_id")
_LIST_ROLES_PAGED = text(_ROLES_SELECT + "ORDER BY r.role_id LIMIT :limit OFFSET :offset")
_COUNT_ROLES = text("SELECT count(*) FROM agent_role")


def _normalize_scopes(rows: list[dict[str, Any]]) -> None:
    # array_agg 在部分驱动下返回 "{a,b}" 字符串，统一成列表
    for row in rows:
        scopes = row.get("scopes")
        if isinstance(scopes, str):
            scopes = [s for s in scopes.strip("{}").split(",") if s]
        row["scopes"] = list(scopes or [])


# todo asyncpg 扩展协议下 "IS NULL + cast" 无法推断参数类型，需显式声明
_MEMBER_BINDS = (
    bindparam("tenant_id", type_=Integer),
    bindparam("username", type_=String),
    bindparam("username_pattern", type_=String),
    bindparam("created_from", type_=String),
    bindparam("created_to", type_=String),
)
_LIST_TENANT_MEMBERS = text("""
SELECT u.id AS id, u.username, u.name, aut.tenant_id, u.create_at, u.updated_at,
       r.name AS role_name
FROM agent_user_tenant aut
JOIN "agent_user" u ON u.id = aut.user_id
JOIN agent_role r ON r.role_id = aut.role_id
WHERE aut.tenant_id = :tenant_id
  AND (:username IS NULL OR u.username ILIKE :username_pattern)
  AND (:created_from IS NULL OR u.create_at::date >= CAST(:created_from AS date))
  AND (:created_to IS NULL OR u.create_at::date <= CAST(:created_to AS date))
ORDER BY (r.name = 'tenant_admin') DESC, u.id DESC LIMIT :limit OFFSET :offset
""").bindparams(
    *_MEMBER_BINDS,
    bindparam("limit", type_=Integer),
    bindparam("offset", type_=Integer),
)
_COUNT_TENANT_MEMBERS = text("""
SELECT COUNT(*)
FROM agent_user_tenant aut
JOIN "agent_user" u ON u.id = aut.user_id
JOIN agent_role r ON r.role_id = aut.role_id
WHERE aut.tenant_id = :tenant_id
  AND (:username IS NULL OR u.username ILIKE :username_pattern)
  AND (:created_from IS NULL OR u.create_at::date >= CAST(:created_from AS date))
  AND (:created_to IS NULL OR u.create_at::date <= CAST(:created_to AS date))
""").bindparams(*_MEMBER_BINDS)

# 取某用户在某租户的角色名（改/解绑前校验归属与防自锁）
_GET_MEMBERSHIP = text("""
SELECT r.name AS role_name
FROM agent_user_tenant aut
JOIN agent_role r ON r.role_id = aut.role_id
WHERE aut.user_id = :user_id AND aut.tenant_id = :tenant_id
""")

# 角色名 → role_id（代码一律按 name 判定，不直接写数字）
_GET_ROLE_ID = text("SELECT role_id FROM agent_role WHERE name = :name")

# 覆盖写角色权限点前清空
_DELETE_ROLE_PERMS = text("DELETE FROM agent_role_permission WHERE role_id = :role_id")


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
            # 先清空内置角色旧权限，再按 DEFAULT_ROLES 当前定义全覆盖写入，
            # 保证库里权限点与代码定义「同步」（缺的补、多的删）。
            role_ids = [r[0] for r in roles]
            if role_ids:
                await execute_write(
                    session,
                    text("DELETE FROM agent_role_permission WHERE role_id = ANY(:role_ids)"),
                    {"role_ids": role_ids},
                )
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
        """取用户在某租户的身份快照（角色名、权限点）。

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

    @staticmethod
    async def get_super_admin_identity(user_id: int) -> dict[str, Any] | None:
        async with session_scope() as session:
            row = await fetch_one(session, _GET_SUPER_ADMIN, {"user_id": user_id})
        if row is None:
            return None
        _normalize_scopes([row])
        return row

    @staticmethod
    async def get_user_assignments(user_id: int) -> list[dict[str, Any]]:
        async with session_scope() as session:
            rows = await fetch_all(session, _GET_USER_ASSIGNMENTS, {"user_id": user_id})
        _normalize_scopes(rows)
        return rows

    @staticmethod
    async def list_roles_with_permissions() -> list[dict[str, Any]]:
        async with session_scope() as session:
            rows = await fetch_all(session, _LIST_ROLES_PERMS)
        _normalize_scopes(rows)
        return rows

    @staticmethod
    async def list_roles_paged(
        page: int = 1, page_size: int = 20
    ) -> tuple[list[dict[str, Any]], int]:
        async with session_scope() as session:
            rows, total = await fetch_page(
                session,
                _LIST_ROLES_PAGED,
                _COUNT_ROLES,
                page=page,
                page_size=page_size,
            )
        _normalize_scopes(rows)
        return rows, total

    @staticmethod
    async def get_role_id(name: str) -> int | None:
        async with session_scope() as session:
            return await fetch_value(session, _GET_ROLE_ID, {"name": name})

    @staticmethod
    async def set_role_permissions(role_id: int, scopes: list[str]) -> None:
        """覆盖角色权限点：先清空再插入，单事务提交（§6.5 改权限即时生效）。"""
        async with session_scope() as session:
            await execute_write(session, _DELETE_ROLE_PERMS, {"role_id": role_id})
            for s in scopes:
                await execute_write(session, _INSERT_PERMISSION, {"role_id": role_id, "scope": s})
            await session.commit()

    @staticmethod
    async def update_role(
        role_id: int, name: str, description: str | None, *, user_id: int
    ) -> None:
        """改角色名称/说明（权限点走 set_role_permissions，不在此处）。

        两条业务约束：
        - admin 为内置锚点，鉴权按 name 判定，不允许改名（改后超管身份失效）；
        - agent_role.name 在库里没有唯一约束，重复名会让人分不清角色，这里显式拦。
        """
        async with session_scope() as session:
            row = await fetch_one(
                session,
                text("SELECT name FROM agent_role WHERE role_id = :role_id"),
                {"role_id": role_id},
            )
            if row is None:
                raise BizException(ErrCode.NOT_FOUND, "角色不存在")
            if row["name"] == "admin" and name != "admin":
                raise BizException(ErrCode.PARAM_ERROR, "内置角色 admin 不可改名")
            dup = await fetch_one(
                session,
                text("SELECT role_id FROM agent_role WHERE name = :name AND role_id <> :role_id"),
                {"name": name, "role_id": role_id},
            )
            if dup is not None:
                raise BizException(ErrCode.PARAM_ERROR, f"角色名已存在: {name}")
            await execute_write(
                session,
                _UPDATE_ROLE,
                {
                    "role_id": role_id,
                    "name": name,
                    "description": description or "",
                    "update_user_id": user_id,
                },
            )
            await session.commit()

    @staticmethod
    async def next_role_id() -> int:
        """取 agent_role 当前最大 role_id + 1（业务键自增，非序列）。"""
        async with session_scope() as session:
            return int(
                await fetch_value(
                    session, text("SELECT COALESCE(MAX(role_id), 0) + 1 FROM agent_role")
                )
            )

    @staticmethod
    async def create_role(
        name: str, description: str | None, scopes: list[str], *, user_id: int
    ) -> int:
        """新建角色并写入权限点；返回新 role_id。"""
        audit = audit_on_insert(user_id=user_id, with_tenant=False)
        role_id = await RbacDao.next_role_id()
        async with session_scope() as session:
            await execute_write(
                session,
                _INSERT_ROLE,
                {"role_id": role_id, "name": name, "description": description, **audit},
            )
            for s in scopes:
                await execute_write(session, _INSERT_PERMISSION, {"role_id": role_id, "scope": s})
            await session.commit()
        return role_id

    @staticmethod
    async def delete_role(role_id: int) -> None:
        """删除角色（含权限点）；admin 为内置角色不可删，其余角色由前端创建均可删。

        按角色名判定（不用 role_id 数字）：admin 是平台超管锚点，删除会破坏授权体系。
        """
        async with session_scope() as session:
            row = await fetch_one(
                session,
                text("SELECT name FROM agent_role WHERE role_id = :role_id"),
                {"role_id": role_id},
            )
            if row is None:
                raise BizException(ErrCode.NOT_FOUND, "角色不存在")
            if row["name"] == "admin":
                raise BizException(ErrCode.PARAM_ERROR, "内置角色 admin 不可删除")
            await execute_write(session, _DELETE_ROLE_PERMS, {"role_id": role_id})
            await execute_write(
                session,
                text("DELETE FROM agent_role WHERE role_id = :role_id"),
                {"role_id": role_id},
            )
            await session.commit()

    @staticmethod
    async def assign_role(user_id: int, tenant_id: int, role_id: int) -> None:
        """普通分配/改角色（student/teacher），PK 冲突即更新。"""
        await RbacDao.upsert_membership(user_id, tenant_id, role_id)

    @staticmethod
    async def get_membership(user_id: int, tenant_id: int) -> str | None:
        """取用户在某租户的角色名（租户管理员改/解绑前校验归属与防自锁）。"""
        async with session_scope() as session:
            row = await fetch_one(
                session, _GET_MEMBERSHIP, {"user_id": user_id, "tenant_id": tenant_id}
            )
        return row["role_name"] if row else None

    @staticmethod
    async def delete_membership(user_id: int, tenant_id: int) -> int:
        """从租户解绑用户（不删 user 记录）。返回受影响行数。"""
        async with session_scope() as session:
            n = await execute_write(
                session,
                text(
                    "DELETE FROM agent_user_tenant "
                    "WHERE user_id = :user_id AND tenant_id = :tenant_id"
                ),
                {"user_id": user_id, "tenant_id": tenant_id},
            )
            await session.commit()
            return n

    @staticmethod
    async def list_tenant_members(
        tenant_id: int,
        *,
        username: str | None = None,
        created_from: str | None = None,
        created_to: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        params: dict[str, Any] = {
            "tenant_id": tenant_id,
            "username": username or None,
            "username_pattern": f"%{username}%" if username else None,
            "created_from": created_from,
            "created_to": created_to,
        }
        async with session_scope() as session:
            return await fetch_page(
                session,
                _LIST_TENANT_MEMBERS,
                _COUNT_TENANT_MEMBERS,
                params,
                page=page,
                page_size=page_size,
            )

    @staticmethod
    async def set_tenant_admin(tenant_id: int, user_id: int) -> int | None:
        """原子更换租户管理员：移除原管理员，再写入新 tenant_admin（不再降级为 student，
        避免依赖 student 角色——角色体系仅保留 admin，其余由前端创建）。

        返回被移除的原管理员 user_id（无则 None）。同一事务保证不出现 0 或 2 个管理员的中间态。
        """
        admin_id = await RbacDao.get_role_id("tenant_admin")
        if admin_id is None:
            raise BizException(
                ErrCode.PARAM_ERROR,
                "租户管理员角色(tenant_admin)不存在，请先在角色管理创建该角色",
            )
        async with session_scope() as session:
            old = await fetch_one(
                session,
                text(
                    "SELECT user_id FROM agent_user_tenant "
                    "WHERE tenant_id = :tenant_id AND role_id = :admin_role_id"
                ),
                {"tenant_id": tenant_id, "admin_role_id": admin_id},
            )
            replaced = old["user_id"] if old else None
            if replaced is not None and replaced != user_id:
                await execute_write(
                    session,
                    text(
                        "DELETE FROM agent_user_tenant "
                        "WHERE tenant_id = :tenant_id AND role_id = :admin_role_id"
                    ),
                    {"tenant_id": tenant_id, "admin_role_id": admin_id},
                )
                await execute_write(
                    session,
                    _UPSERT_MEMBERSHIP,
                    {"user_id": user_id, "tenant_id": tenant_id, "role_id": admin_id},
                )
            await session.commit()
        return replaced
