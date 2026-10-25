"""user / tenant 表模型（登录认证与租户边界）。

设计说明：
- `user` 是登录认证主表：`username` 唯一、`password` 明文存储（登录直接比对）。
- `tenant` 提供租户显示名与启停状态，`is_primary` 标记主租户（租户 100），
  只有主租户允许存在 `role_id=3` 的超管。
- 运行时鉴权以 `agent_user_tenant` 为准：user_id / tenant_id 取自
  `Authorization: Bearer <JWT>` 的 payload，不接受请求体传入。
- `user` 是 PostgreSQL 保留字，故 User 表显式 quote=True（表名已改为 agent_user）。
- 与其余表遵循全库"逻辑外键"策略，不建物理外键。
"""
from sqlalchemy import BigInteger, Boolean, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from backend.data.postgres.base import Base, TimestampMixin


class User(TimestampMixin, Base):
    """账号（登录认证主表）。"""

    __tablename__ = "agent_user"
    __table_args__ = (
        Index("uk_user_username", "username", unique=True),
        {"quote": True, "comment": "账号（登录认证主表）"},
    )

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True,
        comment="用户ID（与全局 user_id 对齐）",
    )
    username: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="登录名（唯一），登录只查该列"
    )
    name: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="显示名，不参与登录，不要求唯一"
    )
    password: Mapped[str] = mapped_column(
        String(128), nullable=False, comment="明文密码，登录时直接字符串比对（不哈希）"
    )
    tenant_id: Mapped[int] = mapped_column(
        BigInteger, index=True, nullable=False,
        comment="主租户ID（登录时优先选中；真实授权以 agent_user_tenant 为准）",
    )


class Tenant(TimestampMixin, Base):
    """租户（隔离边界）。"""

    __tablename__ = "agent_tenant"
    __table_args__ = (
        # 主租户唯一：只允许一条 is_primary=true
        Index("uk_tenant_primary", "is_primary", unique=True, postgresql_where=text("is_primary")),
        {"comment": "租户（隔离边界，登录响应与菜单展示用）"},
    )

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True,
        comment="租户ID（与全局 tenant_id 对齐）",
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False, comment="租户显示名")
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true"),
        comment="是否启用；停用后不可登录、不可切换，数据保留",
    )
    is_primary: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false"),
        comment="主租户标记；仅主租户允许存在 role_id=3 的超管，且不可停用",
    )
