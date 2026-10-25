"""HITL / 转人工队列。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, String, UUID, text
from sqlalchemy.orm import Mapped, mapped_column

from backend.data.postgres.base import TimestampMixin, Base


class AgentEscalation(TimestampMixin, Base):
    """人工队列。"""

    __tablename__ = "agent_escalation"
    __table_args__ = {"comment": "人工转接队列（HITL）"}

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, server_default=text("uuid_generate_v4()"),
        comment="主键（UUID）",
    )
    tenant_id: Mapped[int] = mapped_column(BigInteger, index=True, comment="租户ID（隔离边界，BigInteger）")
    user_id: Mapped[int] = mapped_column(BigInteger, index=True, comment="用户ID（转接人，BigInteger）")
    thread_id: Mapped[str] = mapped_column(UUID(as_uuid=False), index=True, comment="关联会话ID")
    reason: Mapped[str] = mapped_column(String(255), default="", comment="转接原因")
    status: Mapped[str] = mapped_column(String(32), default="pending", comment="状态（pending/resolved）")
    # 处理人：待接手为 NULL（不再用空串表示"未分配"）
    assigned_user_id: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True, index=True, comment="处理人ID（user_id，未分配为空）"
    )
    resolved_at: Mapped[datetime] = mapped_column(DateTime, nullable=True, comment="解决时间")
