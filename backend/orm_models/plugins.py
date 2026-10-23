"""插件注册表（持久化视角，运行时以 PluginRegistry 为准）。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.orm_models.base import Base


class AgentPluginModel(Base):
    """能力/插件注册表。"""

    __tablename__ = "agent_plugin"

    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    version: Mapped[str] = mapped_column(String(32), default="")
    capabilities: Mapped[str] = mapped_column(Text, default="[]")  # JSON list
    status: Mapped[str] = mapped_column(String(32), default="enabled")
    config: Mapped[str] = mapped_column(Text, default="{}")  # JSON
    registered_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
