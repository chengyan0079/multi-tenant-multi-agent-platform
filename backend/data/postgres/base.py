"""SQLAlchemy 声明基类：**仅用于生成 DDL**，运行期不参与数据访问。

`scripts/gen_schema.py` 导入这里的模型来产出 `scripts/schema.sql`；
业务代码一律走 `backend/data/dao/` 的 `text()`，不再 flush ORM 对象。

因此：
- 审计列在这里只定义列、不定义默认值——DDL 也就不会带 DEFAULT；
- 审计值由 `backend/data/sql/audit.py` 在写 SQL 时注入；
- `updated_at` 由库触发器 `set_updated_at()` 刷新，模型上的 `onupdate` 对运行期无效，
  这里不再写，避免让人以为 ORM 还参与更新。
"""
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
        "updated_at", DateTime, nullable=False, server_default=func.now(),
        comment="更新时间（更新时由库触发器刷新）",
    )
    create_user_id: Mapped[int] = mapped_column(
        "create_user_id", BigInteger, nullable=False, comment="创建人ID（写 SQL 时注入）"
    )
    update_user_id: Mapped[int] = mapped_column(
        "update_user_id", BigInteger, nullable=False, comment="更新人ID（写 SQL 时注入）"
    )
    create_tenant_id: Mapped[int] = mapped_column(
        "create_tenant_id", BigInteger, nullable=False, comment="创建租户ID（写 SQL 时注入）"
    )
    update_tenant_id: Mapped[int] = mapped_column(
        "update_tenant_id", BigInteger, nullable=False, comment="更新租户ID（写 SQL 时注入）"
    )


class TimestampMixin:
    """仅时间戳列（API 日志、配置审批流这类系统表）。"""

    create_at: Mapped[datetime] = mapped_column(
        "create_at", DateTime, nullable=False, server_default=func.now(), comment="创建时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        "updated_at", DateTime, nullable=False, server_default=func.now(),
        comment="更新时间（更新时由库触发器刷新）",
    )


class AuditUserOnlyMixin:
    """只有用户审计列、无租户列（全局表，如角色目录）。"""

    create_at: Mapped[datetime] = mapped_column(
        "create_at", DateTime, nullable=False, server_default=func.now(), comment="创建时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        "updated_at", DateTime, nullable=False, server_default=func.now(),
        comment="更新时间（更新时由库触发器刷新）",
    )
    create_user_id: Mapped[int] = mapped_column(
        "create_user_id", BigInteger, nullable=False, comment="创建人ID（写 SQL 时注入）"
    )
    update_user_id: Mapped[int] = mapped_column(
        "update_user_id", BigInteger, nullable=False, comment="更新人ID（写 SQL 时注入）"
    )
