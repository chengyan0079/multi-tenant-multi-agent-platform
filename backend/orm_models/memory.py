"""长期记忆（Letta 式分页块）。"""
from __future__ import annotations

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.orm_models.base import Base


class AgentLongTermMemory(Base):
    """长期记忆块。"""

    __tablename__ = "agent_long_term_memory"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    agent_id: Mapped[str] = mapped_column(String(64), default="")
    block: Mapped[str] = mapped_column(String(32), default="")  # 人设/事实/偏好/摘要
    content: Mapped[str] = mapped_column(Text, default="")
    embedding_id: Mapped[str] = mapped_column(String(64), default="")
