"""Outbox（本地消息表）与死信落库。

见 docs/消息队列对接设计 §6.4（Outbox）与 §7（死信）。

- `AgentOutbox`：业务写库与写本表同事务；投递协程扫 `pending` 发 MQ，
  成功后标 `sent`，消费端处理完标 `done`，失败超限标 `failed`。
  `id` 同时作为 MQ 消息的 `message_id`，消费端据此做幂等（§6.3）。
- `AgentDeadLetter`：消费重试超限的任务落库，便于排查与告警。
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, String, Text, UUID, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from backend.data.postgres.base import TimestampMixin, Base


class AgentOutbox(TimestampMixin, Base):
    """本地消息表（Outbox）。"""

    __tablename__ = "agent_outbox"
    __table_args__ = (
        # 投递协程只扫 pending；partial 索引减小扫描面
        {"comment": "本地消息表（Outbox）：业务与写本表同事务，投递协程扫 pending 发 MQ"},
    )

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, server_default=text("uuid_generate_v4()"),
        comment="主键（UUID，同时作为 MQ 消息 message_id）",
    )
    topic: Mapped[str] = mapped_column(String(64), index=True, comment="消息 type / routing_key，如 audit.flush")
    message_kind: Mapped[str] = mapped_column(
        String(16), default="task", server_default=text("'task'"), index=True,
        comment="投递语义：task（工作队列/竞争消费）| broadcast（发布订阅/每副本一份）；由 routing.Kind 推导",
    )
    payload: Mapped[dict] = mapped_column(JSONB, comment="完整消息体（含 tenant_id/user_id/type/payload）")
    status: Mapped[str] = mapped_column(
        String(16), default="pending", server_default=text("'pending'"), index=True,
        comment="pending（待投递）| sent（已发 MQ）| done（消费端已处理）| failed（消费失败超限）",
    )
    retry_count: Mapped[int] = mapped_column(
        BigInteger, default=0, server_default=text("0"), comment="投递 / 消费重试次数"
    )
    last_error: Mapped[str | None] = mapped_column(Text, comment="最近一次失败原因")
    tenant_id: Mapped[int | None] = mapped_column(BigInteger, comment="租户ID（冗余，便于排查）")
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="投递到 MQ 的时间")


class AgentDeadLetter(TimestampMixin, Base):
    """死信落库（消费重试超限的任务）。"""

    __tablename__ = "agent_dead_letter"
    __table_args__ = {"comment": "死信落库（消费重试超限，便于排查与告警）"}

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, server_default=text("uuid_generate_v4()"),
        comment="主键",
    )
    topic: Mapped[str] = mapped_column(String(64), comment="消息 type")
    payload: Mapped[dict] = mapped_column(JSONB, comment="消息体")
    origin_queue: Mapped[str | None] = mapped_column(String(64), comment="来源队列")
    error: Mapped[str | None] = mapped_column(Text, comment="最终失败原因")
    retry_count: Mapped[int] = mapped_column(BigInteger, default=0, comment="重试次数")
    tenant_id: Mapped[int | None] = mapped_column(BigInteger, comment="租户ID")
