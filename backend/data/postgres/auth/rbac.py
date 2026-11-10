"""RBAC 关系模型：agent_role / agent_role_permission / agent_user_tenant（多对多，无物理外键）。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from backend.data.postgres.base import AuditUserOnlyMixin, Base


class AgentRole(AuditUserOnlyMixin, Base):
    """角色目录（全局定义，tenant 无关）。"""

    __tablename__ = "agent_role"
    __table_args__ = {"comment": "角色目录（全局）"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, comment="主键（代理键）")
    role_id: Mapped[int] = mapped_column(
        Integer, nullable=False, unique=True, comment="角色ID（整数业务键，见 DEFAULT_ROLES）"
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False, comment="角色展示名")
    description: Mapped[str] = mapped_column(Text, default="", comment="角色说明")


class AgentRolePermission(Base):
    """角色→scope 权限映射（全局，按 role_id）。scope 形如 qa:ask / exam:update / *（资源:动作）。"""

    __tablename__ = "agent_role_permission"
    __table_args__ = {"comment": "角色→权限点映射（多对多中间表）"}

    role_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, comment="角色ID（整数；逻辑外键→agent_role.role_id，代码控制）"
    )
    scope: Mapped[str] = mapped_column(
        String(128), primary_key=True, comment="权限点（资源:动作，如 qa:ask）"
    )


class AgentUserTenant(Base):
    """用户-租户-角色分配；PK=(user_id, tenant_id) 强制单租户内只任一角色。

    角色口径：role_id 含义以 agent_role 为准；超管（admin）不写此表，其身份由 agent_user.is_super_admin 标记；普通用户/租户管理员按角色名关联。
    两个部分唯一索引在库层兜住「超管唯一」与「每租户一个管理员」。
    """

    __tablename__ = "agent_user_tenant"
    __table_args__ = (
        # 每租户至多 1 个租户管理员（5）
        Index(
            "uk_aut_tenant_admin",
            "tenant_id",
            unique=True,
            postgresql_where=text("role_id = 5"),
        ),
        {"comment": "用户-租户-角色分配（多对多中间表）"},
    )

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        comment="用户ID（BigInteger，取自 JWT 的 user_id，不接受请求体传入）",
    )
    tenant_id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        comment="租户ID（BigInteger，隔离边界，取自 JWT 的 tenant_id）",
    )
    role_id: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="该用户在租户内的唯一角色：1/2 普通用户、5 租户管理员（每租户唯一）；超管不写本表",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, comment="分配时间"
    )
