"""会话/任务表。"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import BigInteger, Index, String, UUID, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from backend.data.postgres.base import TimestampMixin, Base


class AgentThread(TimestampMixin, Base):
    """一次会话/任务。"""

    __tablename__ = "agent_thread"
    __table_args__ = (
        Index("ix_agent_thread_tenant_user", "tenant_id", "user_id"),
        # 看板「活跃会话」按 (租户, 状态, 更新时间) 区间统计，复合索引直接覆盖
        Index("ix_agent_thread_tenant_status_time", "tenant_id", "status", "updated_at"),
        # 同一 (租户, 用户, 图, 会话键) 唯一：支撑 qa 等「按 session find-or-create 线程」，
        # session_key 为 NULL 时允许多个（chat 路径不传会话键），不影响现有 chat 线程。
        UniqueConstraint(
            "tenant_id",
            "user_id",
            "graph_name",
            "session_key",
            name="uq_agent_thread_tenant_user_graph_session",
        ),
        {"comment": "会话/任务"},
    )

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("uuid_generate_v4()"),
        comment="主键（UUID）",
    )
    tenant_id: Mapped[int] = mapped_column(
        BigInteger, index=True, comment="租户ID（隔离边界，BigInteger）"
    )
    # 会话归属用户：同一租户内不同用户的会话互不可见，thread_id 只在属于自己时可复用
    user_id: Mapped[int] = mapped_column(
        BigInteger, index=True, comment="归属用户ID（隔离边界，BigInteger）"
    )
    status: Mapped[str] = mapped_column(
        String(32), default="active", comment="状态（active/archived）"
    )
    graph_name: Mapped[str] = mapped_column(String(64), default="", comment="运行的图名称")
    session_key: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        comment="会话维度键（如 qa 的 session_id），用于同用户多会话区分与 find-or-create",
    )
    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        default="新会话",
        server_default="新会话",
        comment="会话标题（创建默认「新会话」，首问后按问题主题更新）",
    )
