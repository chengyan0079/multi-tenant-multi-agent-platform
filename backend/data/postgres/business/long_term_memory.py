"""长记忆模型：PG 落库，一行一段记忆块；仅用于 gen_schema 产出 DDL。"""

from __future__ import annotations

from sqlalchemy import BigInteger, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.data.postgres.base import Base, TimestampMixin


class LongTermMemory(TimestampMixin, Base):
    """长记忆块（agent 长期上下文 / 用户画像 / 暂存区等）。"""

    __tablename__ = "agent_long_term_memory"

    id: Mapped[int] = mapped_column("id", BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int | None] = mapped_column(
        "tenant_id", Integer, nullable=True, comment="租户ID；平台级为 NULL"
    )
    user_id: Mapped[int | None] = mapped_column(
        "user_id", Integer, nullable=True, comment="用户ID；缺失则视为租户/平台级记忆"
    )
    agent_id: Mapped[str] = mapped_column(
        "agent_id", String(64), nullable=False, comment="智能体ID"
    )
    block: Mapped[str] = mapped_column(
        "block",
        String(32),
        nullable=False,
        comment="记忆块标识（如 core / user_profile / scratch）",
    )
    content: Mapped[str] = mapped_column("content", Text, nullable=False, comment="记忆内容")
    token_count: Mapped[int] = mapped_column(
        "token_count", Integer, nullable=False, default=0, comment="内容 token 估算，用于分页"
    )
