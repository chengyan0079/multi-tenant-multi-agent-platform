"""会话/任务表。"""
from __future__ import annotations

from sqlalchemy import BigInteger, Index, String, UUID, text
from sqlalchemy.orm import Mapped, mapped_column

from backend.data.postgres.base import TimestampMixin, Base


class AgentThread(TimestampMixin, Base):
    """一次会话/任务。"""

    __tablename__ = "agent_thread"
    __table_args__ = (
        Index("ix_agent_thread_tenant_user", "tenant_id", "user_id"),
        # 看板「活跃会话」按 (租户, 状态, 更新时间) 区间统计，复合索引直接覆盖
        Index("ix_agent_thread_tenant_status_time", "tenant_id", "status", "updated_at"),
        {"comment": "会话/任务"},
    )

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, server_default=text("uuid_generate_v4()"),
        comment="主键（UUID）",
    )
    tenant_id: Mapped[int] = mapped_column(BigInteger, index=True, comment="租户ID（隔离边界，BigInteger）")
    # 会话归属用户：同一租户内不同用户的会话互不可见，thread_id 只在属于自己时可复用
    user_id: Mapped[int] = mapped_column(BigInteger, index=True, comment="归属用户ID（隔离边界，BigInteger）")
    status: Mapped[str] = mapped_column(String(32), default="active", comment="状态（active/archived）")
    graph_name: Mapped[str] = mapped_column(String(64), default="", comment="运行的图名称")
