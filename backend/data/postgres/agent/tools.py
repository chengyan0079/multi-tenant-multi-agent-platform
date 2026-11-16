"""工具目录（租户级）。"""

from __future__ import annotations

from sqlalchemy import UUID, BigInteger, Boolean, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from backend.data.postgres.base import TimestampMixin, Base


class AgentTool(TimestampMixin, Base):
    """工具目录（tenant_id + name 唯一，enabled 由租户控制）。"""

    __tablename__ = "agent_tool"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_agent_tool_tenant_name"),
        {"comment": "工具目录"},
    )

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
        comment="主键（UUID）",
    )
    tenant_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, index=True, comment="所属租户ID"
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False, comment="工具名")
    plugin: Mapped[str] = mapped_column(String(64), default="", comment="所属插件")
    description: Mapped[str] = mapped_column(Text, default="", comment="描述")
    schema: Mapped[str] = mapped_column(Text, default="{}", comment="工具Schema（JSON）")
    config: Mapped[str] = mapped_column(
        Text, default="{}", comment="工具运行配置（JSON：provider/api_key/endpoint 等）"
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("true"),
        comment="租户内是否启用（租户可控制）",
    )
