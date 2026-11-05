"""长记忆（PG 落库，Letta 式分页块）。

原长期/语义记忆走 Milvus，现按决策迁到 PG（Milvus 仅用于文档 RAG 向量检索）。
一行 = 一段长期记忆块；按 租户 + 用户 + 智能体 + block 归属，检索按同条件过滤。

模型仅用于 `scripts/gen_schema.py` 产出 DDL；运行期访问一律走 `long_term_memory_dao` 的 `text()`。
"""
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
        "block", String(32), nullable=False, comment="记忆块标识（如 core / user_profile / scratch）"
    )
    content: Mapped[str] = mapped_column("content", Text, nullable=False, comment="记忆内容")
    token_count: Mapped[int] = mapped_column(
        "token_count", Integer, nullable=False, default=0, comment="内容 token 估算，用于分页"
    )
