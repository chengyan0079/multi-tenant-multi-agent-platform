"""统一会话历史（唯一会话历史源）。

一张表承载全部 Agent 的轮次事件（路由决策 / token / 任务进度 / 任务结果 …），
与具体 Agent 的 State 解耦：新增 Agent 或事件类型只改 `agent_type` / `event_type`
开放字符串与 `payload` JSON，无需 DDL 变更。
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import (
    JSON,
    BigInteger,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    UUID,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.data.postgres.base import AuditMixin, Base


class AgentUnifiedTurn(AuditMixin, Base):
    """统一会话历史的一轮记录（turn_id）。"""

    __tablename__ = "agent_unified_turn"
    __table_args__ = (
        # 一次请求的三段隔离键 + 轮次号，支撑分页/回放/审计
        Index("ix_unified_turn_owner", "tenant_id", "user_id", "thread_id", "turn_index"),
        Index("ix_unified_turn_trace", "trace_id"),
        Index("ix_unified_turn_agent", "tenant_id", "agent_type", "create_at"),
        UniqueConstraint("thread_id", "turn_index", name="uq_unified_turn_thread_index"),
        {"comment": "统一会话历史（唯一会话历史源）"},
    )

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
        comment="turn_id（主键 UUID）",
    )
    tenant_id: Mapped[int] = mapped_column(
        BigInteger, index=True, comment="租户ID（隔离边界，BigInteger）"
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, index=True, comment="用户ID（user_id，BigInteger）"
    )
    # = U，逻辑关联 agent_thread.id；物理外键由代码 JOIN 承担（全库无 FK 约束）
    thread_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), index=True, comment="关联 agent_thread.id（=U）"
    )
    trace_id: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, comment="链路追踪ID（与日志/API日志/业务明细/Langfuse 对齐）"
    )
    turn_index: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="会话内轮次序号（单调递增）"
    )
    # 按 spec 动态取值，无 CHECK 约束，新增 Agent 零 DDL 变更
    agent_type: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="Agent 类型（由 spec 动态取值）"
    )
    spec_version: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True, comment="spec 版本（用于回溯当时路由逻辑）"
    )
    event_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        comment="事件类型（routing_decision/token/task_started/task_progress/task_result/...）",
    )
    user_content: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="用户输入（若有）")
    assistant_content: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, comment="助手输出（token 汇总后的完整正文，若有）"
    )
    # 事件原始负载 + 业务产物引用（artifact_type/artifact_id），具体结构见 UnifiedEventPayload
    payload: Mapped[Optional[dict]] = mapped_column(
        JSON, nullable=True, comment="事件负载 + artifact_type/artifact_id"
    )
    # 路由决策快照：label/agent_type/source/confidence/reason/execution_mode/fallback_used
    routing: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True, comment="路由决策快照")
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="success", comment="轮次态（success/stopped/failed）"
    )
    error_code: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, comment="错误码")
    error_msg: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="错误信息")
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, comment="端到端耗时（毫秒）")
    token_usage: Mapped[Optional[dict]] = mapped_column(
        JSON, nullable=True, comment="Token 用量（JSON：prompt/completion/total）"
    )
