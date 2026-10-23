"""
rbac - 角色/权限解析服务（设计文档 §9.1 ③ RBAC；无登录：身份由上游网关断言，后端只做授权）

职责：
- resolve(user_id, tenant_id)：查 agent_user_tenant → agent_role → agent_role_permission，给出
  (role_name, scopes[])。后端据此做 require_role / require_scope，不信任网关带来的角色。
- ensure_default_roles()：幂等写入内置角色(student/teacher/admin)与权限点（全局，tenant 无关）。
- assign(user_id, tenant_id, role_id)：一人一租户一角色（PK 冲突即更新）。

权限点词汇（scope）：qa:chat / interview:run / resume:review:self / resume:review:any /
exam:grade / hitl:approve / class:view / config:manage / audit:view；"*" 表示全部。
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import select

from backend.app_state import app_state
from backend.common.logger import get_logger
from backend.orm_models.base import Base
from backend.orm_models.rbac import AgentRole, AgentRolePermission, AgentUserTenant
from backend.orm_models import session_scope

logger = get_logger("rbac")

# 内置角色 → 权限点（默认目录；admin 用 "*" 通配全部）。
# 注意：本常量仅作为 ensure_default_roles() 的「种子源」写入数据库，
# 请求期授权解析一律以 agent_role_permission 表为准，本常量不参与任何兜底。
DEFAULT_ROLE_SCOPES: dict[str, list[str]] = {
    "student": ["qa:chat", "interview:run", "resume:review:self", "trace:view:self"],
    "teacher": [
        "qa:chat", "interview:run",
        "resume:review:self", "resume:review:any",
        "exam:grade", "hitl:approve", "class:view",
    ],
    "admin": ["*"],
}


class RbacService:
    """角色/权限解析（无状态，纯查库 + 内置目录）。"""

    @staticmethod
    async def ensure_default_roles() -> None:
        """幂等写入内置角色与权限点（全局，tenant 无关）。启动或租户开通时调用。"""
        async with session_scope() as s:
            existing = (await s.execute(select(AgentRole.role_id))).scalars().all()
            have = set(existing)
            for role_id, scopes in DEFAULT_ROLE_SCOPES.items():
                if role_id not in have:
                    s.add(AgentRole(role_id=role_id, name=role_id, description=f"内置角色 {role_id}"))
            # 权限点：按 (role_id, scope) upsert
            have_perms = set(
                (r.role_id, r.scope)
                for r in (await s.execute(select(AgentRolePermission))).scalars().all()
            )
            for role_id, scopes in DEFAULT_ROLE_SCOPES.items():
                for scope in scopes:
                    if (role_id, scope) not in have_perms:
                        s.add(AgentRolePermission(role_id=role_id, scope=scope))
            await s.commit()
        logger.info("内置角色与权限点已确保")

    @staticmethod
    async def resolve(user_id: str, tenant_id: str) -> Optional[tuple[str, list[str]]]:
        """解析用户在租户内的 (角色名, 权限点[])。无分配返回 None（由调用方决定 403 或开发兜底）。"""
        async with session_scope() as s:
            row = (
                await s.execute(
                    select(AgentUserTenant).where(
                        AgentUserTenant.user_id == user_id,
                        AgentUserTenant.tenant_id == tenant_id,
                    )
                )
            ).scalar_one_or_none()
            if row is None:
                return None
            role = (
                await s.execute(select(AgentRole).where(AgentRole.role_id == row.role_id))
            ).scalar_one_or_none()
            role_name = role.name if role else row.role_id
            perms = (
                await s.execute(
                    select(AgentRolePermission.scope).where(AgentRolePermission.role_id == row.role_id)
                )
            ).scalars().all()
            return role_name, list(perms)

    @staticmethod
    async def assign(user_id: str, tenant_id: str, role_id: str) -> None:
        """分配/更新 用户-租户-角色（PK 冲突即更新，保证单租户内只任一角色）。"""
        async with session_scope() as s:
            existing = (
                await s.execute(
                    select(AgentUserTenant).where(
                        AgentUserTenant.user_id == user_id,
                        AgentUserTenant.tenant_id == tenant_id,
                    )
                )
            ).scalar_one_or_none()
            if existing is None:
                s.add(AgentUserTenant(user_id=user_id, tenant_id=tenant_id, role_id=role_id))
            else:
                existing.role_id = role_id
            await s.commit()
        logger.info(f"分配角色 user={user_id} tenant={tenant_id} role={role_id}")
