"""登录日志模型（agent_login_log）：每次登录尝试一行，含失败记录，user_id 可空。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.data.postgres.base import Base


class AgentLoginLog(Base):
    """登录日志（不含 updated_at：登录事件写入后不再变更）。"""

    __tablename__ = "agent_login_log"
    __table_args__ = (
        Index("ix_agent_login_log_user_time", "user_id", "create_at"),
        Index("ix_agent_login_log_tenant_time", "tenant_id", "create_at"),
        Index("ix_agent_login_log_create_at", "create_at"),
        {"comment": "登录日志（每次登录尝试一行，成功与失败都记）"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, comment="主键")
    user_id: Mapped[int | None] = mapped_column(BigInteger, comment="用户ID（登录失败时可能为空）")
    username: Mapped[str | None] = mapped_column(
        String(64), comment="尝试登录的用户名（失败时保留输入值，用于排查撞库）"
    )
    tenant_id: Mapped[int | None] = mapped_column(BigInteger, comment="租户ID（超管与失败为空）")
    login_type: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="password", comment="登录方式（password/sso）"
    )
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, comment="是否登录成功")
    fail_reason: Mapped[str | None] = mapped_column(String(128), comment="失败原因")
    ip: Mapped[str | None] = mapped_column(
        String(64), comment="客户端IP（X-Forwarded-For首段优先）"
    )
    user_agent: Mapped[str | None] = mapped_column(String(512), comment="User-Agent原文")
    client: Mapped[str | None] = mapped_column(
        String(64), comment="从 UA 解析出的客户端（如 Chrome / Windows）"
    )
    trace_id: Mapped[str | None] = mapped_column(String(64), comment="链路追踪ID")
    create_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), comment="登录时间"
    )
