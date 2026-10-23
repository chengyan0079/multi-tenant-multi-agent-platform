"""工具目录。"""
from __future__ import annotations

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.orm_models.base import Base


class AgentTool(Base):
    """工具目录。"""

    __tablename__ = "agent_tool"

    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    plugin: Mapped[str] = mapped_column(String(64), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    schema: Mapped[str] = mapped_column(Text, default="{}")  # JSON Schema
