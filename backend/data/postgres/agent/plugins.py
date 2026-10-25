"""插件注册表（持久化视角，运行时以 PluginRegistry 为准）。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, String, Text, UUID, func, text
from sqlalchemy.orm import Mapped, mapped_column

from backend.data.postgres.base import AuditMixin, Base


class AgentPluginModel(AuditMixin, Base):
    """能力/插件注册表。"""

    __tablename__ = "agent_plugin"
    __table_args__ = {"comment": "插件注册表"}

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, server_default=text("uuid_generate_v4()"), comment="主键（UUID）"
    )
    name: Mapped[str] = mapped_column(String(64), unique=True, comment="插件名")
    version: Mapped[str] = mapped_column(String(32), default="", comment="版本")
    capabilities: Mapped[str] = mapped_column(Text, default="[]", comment="能力列表（JSON）")
    status: Mapped[str] = mapped_column(String(32), default="enabled", comment="状态（enabled/disabled）")
    config: Mapped[str] = mapped_column(Text, default="{}", comment="配置（JSON）")
    registered_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), comment="注册时间")
    tenant_id: Mapped[int] = mapped_column(BigInteger, index=True, comment="租户ID（隔离边界，BigInteger）")
    user_id: Mapped[int] = mapped_column(BigInteger, comment="维护人user_id（BigInteger，前端显式维护）")
