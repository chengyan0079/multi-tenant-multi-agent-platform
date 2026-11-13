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
    resolved_user_id: Mapped[int] = mapped_column(
        BigInteger, comment="处理人ID（user_id，BigInteger）"
    )
    resolved_at: Mapped[datetime] = mapped_column(DateTime, comment="解决时间")


# ------------------------- 试卷批改 -------------------------
class QaResult(AuditMixin, Base):
    """问答结果（一次问答一行，供 RAGAS 质量验证）。"""

    __tablename__ = "agent_qa_results"
    __table_args__ = (
        Index("idx_qa_results_tenant_time", "tenant_id", "create_at"),
        Index("idx_qa_results_user_time", "user_id", "create_at"),
        Index("idx_qa_results_trace", "trace_id"),
        Index("idx_qa_results_status", "status"),
        {"comment": "问答结果（一次问答一行，供 RAGAS 质量验证）"},
    )

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
        comment="主键（UUID）",
    )
    trace_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        comment="链路追踪ID（与 agent_api_call_log.trace_id 对齐，可关联）",
    )
    tenant_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, comment="租户ID（隔离边界，BigInteger）"
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, comment="提问用户ID（user_id，BigInteger）"
    )
    # 归属会话：统一历史源 agent_unified_turn.id；一个会话内的多轮问答共享同一 turn_id
    turn_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), nullable=True, index=True, comment="关联 agent_unified_turn.id（唯一历史源、归属会话）"
    )
    agent_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="qa", comment="智能体类型（默认 qa）"
    )
    question: Mapped[str] = mapped_column(
        Text, nullable=False, comment="用户问题（RAGAS user_input）"
    )
    answer: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="模型回答（RAGAS response）"
    )
    answer_mode: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="回答模式（rag/llm_direct/general/fallback）"
    )
    query_type: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="查询类型（如 PRECISE/BROAD）"
    )
    confidence: Mapped[float | None] = mapped_column(
        Numeric(5, 4), nullable=True, comment="置信度（0-1）"
    )
    retrieved_contexts: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
        comment="检索上下文（JSON 数组：content/doc_id/score，RAGAS retrieved_contexts）",
    )
    sources: Mapped[dict | None] = mapped_column(
        JSON, nullable=True, comment="引用来源（JSON，展示用）"
    )
    reference_answer: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="参考答案（RAGAS reference；人工标注或知识库标准答案，可空）"
    )
    latency_ms: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="端到端耗时（毫秒）"
    )
    token_usage: Mapped[dict | None] = mapped_column(
        JSON, nullable=True, comment="Token 用量（JSON：prompt/completion/total）"
    )
    enable_web_search: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, comment="是否启用联网检索"
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="success", comment="执行结果（success/failed/partial）"
    )
    error_msg: Mapped[str | None] = mapped_column(Text, nullable=True, comment="失败原因")
    extra: Mapped[dict | None] = mapped_column(
        JSON, nullable=True, comment="扩展信息（JSON：模型名/图版本/实验标记等）"
    )


# ------------------------- RAGAS 评估结果 -------------------------
class QaRagasEval(AuditMixin, Base):
    """RAGAS 评估结果（一次评估一行，支持同一问答多次评估留痕）。"""

    __tablename__ = "agent_qa_ragas_evals"
    __table_args__ = (
        Index("idx_qa_ragas_qa_result", "qa_result_id"),
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
    qa_result_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), nullable=False, comment="关联 agent_qa_results.id"
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
