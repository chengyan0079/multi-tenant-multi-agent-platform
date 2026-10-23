"""HITL / 转人工队列。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.orm_models.base import Base


class AgentEscalation(Base):
    """人工队列。"""

    __tablename__ = "agent_escalation"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    thread_id: Mapped[str] = mapped_column(String(64), index=True)
    reason: Mapped[str] = mapped_column(String(255), default="")
    status: Mapped[str] = mapped_column(String(32), default="pending")  # pending/resolved
    assigned_to: Mapped[str] = mapped_column(String(64), default="")
    resolved_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
