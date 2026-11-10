"""user/tenant 表模型：登录认证与租户边界；password 明文、超管不挂租户，鉴权以 JWT payload 为准。"""

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
        BigInteger,
        primary_key=True,
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
    tenant_id: Mapped[int | None] = mapped_column(
        BigInteger,
        index=True,
        nullable=True,
        comment="归属租户ID（登录默认选中；超管为 NULL；真实授权以 agent_user_tenant 为准）",
    )


class Tenant(TimestampMixin, Base):
    """租户（隔离边界）。"""

    __tablename__ = "agent_tenant"
    __table_args__ = ({"comment": "租户（隔离边界，登录响应与菜单展示用）"},)

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        comment="租户ID（与全局 tenant_id 对齐）",
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False, comment="租户显示名")
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("true"),
        comment="是否启用；停用后不可登录、不可切换，数据保留",
    )
