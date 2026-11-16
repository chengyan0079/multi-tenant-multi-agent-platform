"""业务元数据表（考试/简历/面试/问答等）：UUID 主键 + AuditMixin + tenant_id 隔离，跨表引用不建物理外键。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    UUID,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.data.postgres.base import AuditMixin, Base


# ------------------------- 知识库待补充队列 -------------------------
class KnowledgePendingQueue(AuditMixin, Base):
    """知识库待补充队列（低置信度问答入队，待人工补充）。"""

    __tablename__ = "agent_knowledge_pending_queue"
    __table_args__ = (
        Index("idx_kpq_tenant_id", "tenant_id"),
        Index("idx_kpq_status", "status"),
        {"comment": "知识库待补充队列"},
    )

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
        comment="主键（UUID）",
    )
    tenant_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, comment="租户ID（隔离边界，BigInteger）"
    )
    question: Mapped[str] = mapped_column(Text, nullable=False, comment="待补充问题")
    user_id: Mapped[int] = mapped_column(BigInteger, comment="提交用户ID（user_id，BigInteger）")
    confidence: Mapped[float] = mapped_column(Float, nullable=False, comment="置信度")
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", comment="状态（pending/resolved/dismissed）"
    )
    # 待审记录尚未被处理时没有处理人/处理时间，必须允许为空
    resolved_user_id: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True, comment="处理人ID（user_id，BigInteger）"
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, comment="解决时间"
    )


# ------------------------- RAGAS 评估结果 -------------------------
class QaRagasEval(AuditMixin, Base):
    """RAGAS 评估结果（一次评估一行，支持同一问答多次评估留痕）。"""

    __tablename__ = "agent_qa_ragas_evals"
    __table_args__ = (
        Index("idx_qa_ragas_turn", "turn_id"),
        Index("idx_qa_ragas_tenant_time", "tenant_id", "eval_at"),
        Index("idx_qa_ragas_trace", "trace_id"),
        Index("idx_qa_ragas_status", "status"),
        {"comment": "RAGAS 评估结果（一次评估一行，支持多次评估留痕）"},
    )

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
        comment="主键（UUID）",
    )
    turn_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        nullable=False,
        index=True,
        comment="关联 agent_unified_turn.id（评测对象）",
    )
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="链路追踪ID")
    tenant_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, comment="租户ID（隔离边界，BigInteger）"
    )
    evaluator: Mapped[str] = mapped_column(
        String(64), nullable=False, default="ragas", comment="评估器（ragas）"
    )
    evaluator_model: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="评估模型（LLM/embedding 名称与版本）"
    )
    dataset_version: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="数据集/标注版本"
    )
    reference_answer: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="人工标准答案（RAGAS 评测输入，必填触发）"
    )
    retrieved_contexts: Mapped[dict | None] = mapped_column(
        JSON, nullable=True, comment="评测时的检索上下文快照（RAGAS context 指标用）"
    )
    faithfulness: Mapped[float | None] = mapped_column(
        Numeric(6, 4), nullable=True, comment="忠实度（回答是否被上下文支持）"
    )
    answer_relevancy: Mapped[float | None] = mapped_column(
        Numeric(6, 4), nullable=True, comment="答案相关性"
    )
    context_precision: Mapped[float | None] = mapped_column(
        Numeric(6, 4), nullable=True, comment="上下文精确率"
    )
    context_recall: Mapped[float | None] = mapped_column(
        Numeric(6, 4), nullable=True, comment="上下文召回率"
    )
    answer_correctness: Mapped[float | None] = mapped_column(
        Numeric(6, 4), nullable=True, comment="答案正确性"
    )
    metrics: Mapped[dict | None] = mapped_column(
        JSON, nullable=True, comment="全量指标（JSON，含自定义/新增指标，避免频繁改表）"
    )
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="pending",
        comment="评估状态（pending/running/success/failed）",
    )
    error_msg: Mapped[str | None] = mapped_column(Text, nullable=True, comment="失败原因")
    eval_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="评估时间")
