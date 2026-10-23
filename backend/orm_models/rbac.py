"""
rbac - 用户/租户/角色三者关系与权限模型（设计文档 §9.0 / §9.1，约束：一用户在单租户只任一角色）

约定（三元关联，角色为全局定义、分配带租户作用域）：
- agent_role           角色目录（全局）：student / teacher / admin 等
- agent_role_permission 角色→scope 权限映射（全局，按 role_id）
- agent_user_tenant    用户-租户-角色 分配，PK=(user_id, tenant_id) → 强制「一用户在单租户只任一角色」
关系基数：租户 1—* 用户、租户 1—* 角色（经分配体现）、角色 1—* 用户（经分配体现）、
用户 *—* 租户（可跨租户），且「同一用户在不同租户可任不同角色」。
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.orm_models.base import Base


class AgentRole(Base):
    """角色目录（全局定义，tenant 无关）。"""

    __tablename__ = "agent_role"

    role_id: Mapped[str] = mapped_column(String(64), primary_key=True, comment="角色ID（如 student/teacher/admin）")
    name: Mapped[str] = mapped_column(String(64), nullable=False, comment="角色展示名")
    description: Mapped[str] = mapped_column(Text, default="", comment="角色说明")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow, comment="创建时间")


class AgentRolePermission(Base):
    """角色→scope 权限映射（全局，按 role_id）。scope 形如 qa:chat / exam:grade / *。"""

    __tablename__ = "agent_role_permission"

    role_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("agent_role.role_id"), primary_key=True, comment="角色ID"
    )
    scope: Mapped[str] = mapped_column(String(128), primary_key=True, comment="权限点（最小粒度）")


class AgentUserTenant(Base):
    """用户-租户-角色分配；PK=(user_id, tenant_id) 强制单租户内只任一角色。"""

    __tablename__ = "agent_user_tenant"

    user_id: Mapped[str] = mapped_column(String(64), primary_key=True, comment="用户ID（由上游网关断言）")
    tenant_id: Mapped[str] = mapped_column(String(64), primary_key=True, comment="租户ID（隔离边界）")
    role_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("agent_role.role_id"), nullable=False, comment="该用户在租户内的唯一角色"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow, comment="分配时间")
