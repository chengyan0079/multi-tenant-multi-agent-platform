"""SQLAlchemy 声明基类：仅用于 scripts/gen_schema.py 生成 DDL，运行期不参与数据访问。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """所有模型公共基类。"""


class AuditMixin:
    """审计列 + 时间戳列（多对多中间表除外，其余表通用）。"""

    create_at: Mapped[datetime] = mapped_column(
        "create_at", DateTime, nullable=False, server_default=func.now(), comment="创建时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        "updated_at",
        DateTime,
        nullable=False,
        server_default=func.now(),
        comment="更新时间（更新时由库触发器刷新）",
    )
    create_user_id: Mapped[int] = mapped_column(
        "create_user_id", BigInteger, nullable=False, comment="创建人ID（写 SQL 时注入）"
    )
    update_user_id: Mapped[int] = mapped_column(
        "update_user_id", BigInteger, nullable=False, comment="更新人ID（写 SQL 时注入）"
    )
    create_tenant_id: Mapped[int | None] = mapped_column(
        "create_tenant_id",
        BigInteger,
        nullable=True,
        comment="创建租户ID（写 SQL 时注入）；超管不挂租户，其操作记 NULL",
    )
    update_tenant_id: Mapped[int | None] = mapped_column(
        "update_tenant_id",
        BigInteger,
        nullable=True,
        comment="更新租户ID（写 SQL 时注入）；超管不挂租户，其操作记 NULL",
    )


class TimestampMixin:
    """仅时间戳列（API 日志、配置审批流这类系统表）。"""

    create_at: Mapped[datetime] = mapped_column(
        "create_at", DateTime, nullable=False, server_default=func.now(), comment="创建时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        "updated_at",
        DateTime,
        nullable=False,
        server_default=func.now(),
        comment="更新时间（更新时由库触发器刷新）",
    )


class AuditUserOnlyMixin:
    """只有用户审计列、无租户列（全局表，如角色目录）。"""

    create_at: Mapped[datetime] = mapped_column(
        "create_at", DateTime, nullable=False, server_default=func.now(), comment="创建时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        "updated_at",
        DateTime,
        nullable=False,
        server_default=func.now(),
        comment="更新时间（更新时由库触发器刷新）",
    )
    create_user_id: Mapped[int] = mapped_column(
        "create_user_id", BigInteger, nullable=False, comment="创建人ID（写 SQL 时注入）"
    )
    update_user_id: Mapped[int] = mapped_column(
        "update_user_id", BigInteger, nullable=False, comment="更新人ID（写 SQL 时注入）"
    )
