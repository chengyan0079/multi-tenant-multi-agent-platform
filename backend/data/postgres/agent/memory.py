"""长期记忆（Letta 式分页块）。"""

from __future__ import annotations

from sqlalchemy import BigInteger, String, Text, UUID, text
from sqlalchemy.orm import Mapped, mapped_column

from backend.data.postgres.base import TimestampMixin, Base


class AgentLongTermMemory(TimestampMixin, Base):
    """长期记忆块。"""

    __tablename__ = "agent_long_term_memory"
    __table_args__ = {"comment": "长期记忆块"}

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
        comment="主键（UUID）",
    )
    tenant_id: Mapped[int] = mapped_column(
        BigInteger, index=True, comment="租户ID（隔离边界，BigInteger）"
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, index=True, comment="用户ID（记忆用户，BigInteger）"
    )
    agent_id: Mapped[str] = mapped_column(String(64), default="", comment="智能体ID")
    block: Mapped[str] = mapped_column(
        String(32), default="", comment="记忆块类型（persona/fact/preference/summary）"
    )
    content: Mapped[str] = mapped_column(Text, default="", comment="记忆内容")
    embedding_id: Mapped[str] = mapped_column(String(64), default="", comment="向量库ID")
