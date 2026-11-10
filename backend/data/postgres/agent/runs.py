"""运行台账（token/成本/延迟）。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, Integer, String, UUID, func, text
from sqlalchemy.orm import Mapped, mapped_column

from backend.data.postgres.base import TimestampMixin, Base


class AgentRun(TimestampMixin, Base):
    """运行台账。"""

    __tablename__ = "agent_run"
    __table_args__ = (
        # 看板按 (租户, 时间) 区间聚合运行量/成本/成功率，必须用复合索引收窄
        Index("ix_agent_run_tenant_time", "tenant_id", "create_at"),
        {"comment": "运行台账（token/成本/延迟）"},
    )

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("uuid_generate_v4()"),
        comment="主键（UUID）",
    )
    tenant_id: Mapped[int] = mapped_column(
        BigInteger, index=True, comment="租户ID（隔离边界，BigInteger）"
    )
    # 冗余会话归属人：按用户维度统计 token/成本时不必回表 agent_thread
    user_id: Mapped[int] = mapped_column(
        BigInteger, index=True, comment="归属用户ID（冗余，BigInteger）"
    )
    thread_id: Mapped[str] = mapped_column(UUID(as_uuid=False), index=True, comment="关联会话ID")
    graph_name: Mapped[str] = mapped_column(String(64), default="", comment="运行的图名称")
    status: Mapped[str] = mapped_column(
        String(32), default="running", comment="运行状态（running/done/error）"
    )
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0, comment="输入token数")
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0, comment="输出token数")
    cost_cents: Mapped[int] = mapped_column(Integer, default=0, comment="成本（分）")
    started_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), comment="开始时间"
    )
    ended_at: Mapped[datetime] = mapped_column(DateTime, nullable=True, comment="结束时间")
