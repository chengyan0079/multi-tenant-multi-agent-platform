"""工具目录。"""

from __future__ import annotations

from sqlalchemy import String, Text, UUID, text
from sqlalchemy.orm import Mapped, mapped_column

from backend.data.postgres.base import TimestampMixin, Base


class AgentTool(TimestampMixin, Base):
    """工具目录。"""

    __tablename__ = "agent_tool"
    __table_args__ = {"comment": "工具目录"}

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("uuid_generate_v4()"),
        comment="主键（UUID）",
    )
    name: Mapped[str] = mapped_column(String(64), unique=True, comment="工具名")
    plugin: Mapped[str] = mapped_column(String(64), default="", comment="所属插件")
    description: Mapped[str] = mapped_column(Text, default="", comment="描述")
    schema: Mapped[str] = mapped_column(Text, default="{}", comment="工具Schema（JSON）")
