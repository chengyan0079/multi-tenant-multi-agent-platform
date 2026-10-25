"""append-only 轨迹（replay/fork）。"""
from __future__ import annotations

from sqlalchemy import BigInteger, String, Text, UUID, text
from sqlalchemy.orm import Mapped, mapped_column

from backend.data.postgres.base import TimestampMixin, Base


class AgentMessage(TimestampMixin, Base):
    """不可变消息轨迹。"""

    __tablename__ = "agent_message"
    __table_args__ = {"comment": "消息轨迹（append-only）"}

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, server_default=text("uuid_generate_v4()"),
        comment="主键（UUID）",
    )
    tenant_id: Mapped[int] = mapped_column(BigInteger, index=True, comment="租户ID（隔离边界，BigInteger）")
    # 冗余会话归属人：隔离查询不必回表 agent_thread，写入方须与 thread.user_id 一致
    user_id: Mapped[int] = mapped_column(BigInteger, index=True, comment="归属用户ID（冗余，BigInteger）")
    thread_id: Mapped[str] = mapped_column(UUID(as_uuid=False), index=True, comment="关联会话ID")
    run_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=True, comment="关联运行ID")
    role: Mapped[str] = mapped_column(String(32), default="", comment="角色（user/assistant/system/tool）")
    type: Mapped[str] = mapped_column(String(32), default="", comment="消息类型")
    payload: Mapped[str] = mapped_column(Text, default="{}", comment="消息内容（JSON）")
