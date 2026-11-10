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
        server_default=text("uuid_generate_v4()"),
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
class Exam(AuditMixin, Base):
    """试卷定义。"""

    __tablename__ = "agent_exams"
    __table_args__ = (
        Index("idx_exams_tenant_id", "tenant_id"),
        {"comment": "试卷定义"},
    )

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("uuid_generate_v4()"),
        comment="主键（UUID）",
    )
    tenant_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, comment="租户ID（隔离边界，BigInteger）"
    )
    title: Mapped[str] = mapped_column(String(256), nullable=False, comment="标题")
    description: Mapped[str] = mapped_column(Text, comment="描述")
    due_date: Mapped[datetime] = mapped_column(DateTime, comment="截止时间")
    created_user_id: Mapped[int] = mapped_column(
        BigInteger, comment="创建人ID（user_id，BigInteger）"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, comment="是否启用"
    )


class Question(AuditMixin, Base):
    """试卷题目。"""

    __tablename__ = "agent_questions"
    __table_args__ = (
        Index("idx_questions_exam_id", "exam_id"),
        Index("idx_questions_knowledge_tag", "knowledge_tag"),
        {"comment": "试卷题目"},
    )

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("uuid_generate_v4()"),
        comment="主键（UUID）",
    )
    tenant_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, comment="租户ID（隔离边界，BigInteger）"
    )
    exam_id: Mapped[str] = mapped_column(UUID(as_uuid=False), comment="所属试卷ID")
    question_no: Mapped[int] = mapped_column(Integer, nullable=False, comment="题号")
    question_type: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        comment="题型（single_choice/multi_choice/judge/short_answer/code）",
    )
    content: Mapped[str] = mapped_column(Text, nullable=False, comment="题干")
    correct_answer: Mapped[str] = mapped_column(Text, comment="标准答案")
    score: Mapped[int] = mapped_column(Integer, nullable=False, default=10, comment="分值")
    knowledge_tag: Mapped[str] = mapped_column(String(128), comment="知识点标签")


class ScoringPoint(AuditMixin, Base):
    """题目评分点。"""

    __tablename__ = "agent_scoring_points"
    __table_args__ = (
        Index("idx_scoring_points_question_id", "question_id"),
        {"comment": "题目评分点"},
    )

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("uuid_generate_v4()"),
        comment="主键（UUID）",
    )
    question_id: Mapped[str] = mapped_column(UUID(as_uuid=False), comment="题目ID")
    point_desc: Mapped[str] = mapped_column(Text, nullable=False, comment="评分点描述")
    point_score: Mapped[int] = mapped_column(Integer, nullable=False, comment="评分点分值")
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, comment="是否启用"
    )
    confirmed_user_id: Mapped[int] = mapped_column(
        BigInteger, comment="确认人ID（user_id，BigInteger）"
    )
    confirmed_at: Mapped[datetime] = mapped_column(DateTime, comment="确认时间")


class ExamSubmission(AuditMixin, Base):
    """试卷提交记录。"""

    __tablename__ = "agent_exam_submissions"
    __table_args__ = (
        UniqueConstraint("exam_id", "user_id", name="uq_exam_submissions_exam_student"),
        Index("idx_exam_submissions_exam_id", "exam_id"),
        Index("idx_exam_submissions_user_id", "user_id"),
        Index("idx_exam_submissions_status", "status"),
        {"comment": "试卷提交记录"},
    )

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("uuid_generate_v4()"),
        comment="主键（UUID）",
    )
    tenant_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, comment="租户ID（隔离边界，BigInteger）"
    )
    exam_id: Mapped[str] = mapped_column(UUID(as_uuid=False), comment="试卷ID")
    user_id: Mapped[int] = mapped_column(BigInteger, comment="用户ID（user_id，BigInteger）")
    source: Mapped[str] = mapped_column(
        String(16), nullable=False, default="word", comment="来源（word/online/miniapp）"
    )
    word_minio_path: Mapped[str] = mapped_column(String(512), comment="Word 文件 MinIO 路径")
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="submitted",
        comment="状态（submitted/ai_processing/pending_review/reviewed/published）",
    )
    submitted_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, comment="提交时间")
    published_at: Mapped[datetime] = mapped_column(DateTime, comment="发布时间")
    weak_points: Mapped[dict] = mapped_column(JSON, comment="薄弱点（JSON）")
    weak_points_summary: Mapped[str] = mapped_column(Text, comment="薄弱点摘要")


class ExamReview(AuditMixin, Base):
    """试卷批改明细（每题一条）。"""

    __tablename__ = "agent_exam_reviews"
    __table_args__ = (
        Index("idx_exam_reviews_submission_id", "submission_id"),
        Index("idx_exam_reviews_knowledge_tag", "knowledge_tag"),
        {"comment": "试卷批改明细（每题一条）"},
    )

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("uuid_generate_v4()"),
        comment="主键（UUID）",
    )
    submission_id: Mapped[str] = mapped_column(UUID(as_uuid=False), comment="提交记录ID")
    question_id: Mapped[str] = mapped_column(UUID(as_uuid=False), comment="题目ID")
    question_type: Mapped[str] = mapped_column(String(16), nullable=False, comment="题型")
    knowledge_tag: Mapped[str] = mapped_column(String(128), comment="知识点标签")
    student_answer: Mapped[str] = mapped_column(Text, comment="学生作答")
    ai_score: Mapped[int] = mapped_column(Integer, comment="AI 评分")
    ai_feedback: Mapped[str] = mapped_column(Text, comment="AI 反馈")
    ai_raw_result: Mapped[dict] = mapped_column(JSON, comment="AI 原始结果（JSON）")
    teacher_score: Mapped[int] = mapped_column(Integer, comment="教师评分")
    teacher_comment: Mapped[str] = mapped_column(Text, comment="教师评语")
    final_score: Mapped[int] = mapped_column(Integer, comment="最终得分")
    needs_review: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, comment="是否需要人工复核"
    )
    reviewed_user_id: Mapped[int] = mapped_column(
        BigInteger, comment="复核人ID（user_id，BigInteger）"
    )
    reviewed_at: Mapped[datetime] = mapped_column(DateTime, comment="复核时间")


# ------------------------- 简历审查 -------------------------
class ResumeReview(AuditMixin, Base):
    """简历审查结果。"""

    __tablename__ = "agent_resume_reviews"
    __table_args__ = (
        Index("idx_resume_reviews_tenant_id", "tenant_id"),
        Index("idx_resume_reviews_user_id", "user_id"),
        Index("idx_resume_reviews_status", "status"),
        {"comment": "简历审查结果"},
    )

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("uuid_generate_v4()"),
        comment="主键（UUID）",
    )
    tenant_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, comment="租户ID（隔离边界，BigInteger）"
    )
    user_id: Mapped[int] = mapped_column(BigInteger, comment="用户ID（user_id，BigInteger）")
    pdf_minio_path: Mapped[str] = mapped_column(
        String(512), nullable=False, comment="PDF 文件 MinIO 路径"
    )
    weighted_score: Mapped[float] = mapped_column(
        Numeric(5, 2), default=0.0, comment="综合加权得分（0-100，由六维度加权计算）"
    )
    structured_data: Mapped[dict | None] = mapped_column(
        JSON, nullable=True, comment="结构化信息（JSON，上传时为空）"
    )
    scores: Mapped[dict | None] = mapped_column(JSON, nullable=True, comment="评分（JSON）")
    issues: Mapped[dict | None] = mapped_column(JSON, nullable=True, comment="问题清单（JSON）")
    summary: Mapped[dict | None] = mapped_column(JSON, nullable=True, comment="摘要（JSON）")
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="pending",
        comment="状态（pending/processing/done/failed）",
    )
    error_msg: Mapped[str] = mapped_column(Text, default="", comment="错误信息")


# ------------------------- 模拟面试 -------------------------
class InterviewQuestion(AuditMixin, Base):
    """面试题库。"""

    __tablename__ = "agent_interview_questions"
    __table_args__ = (
        Index("idx_interview_questions_tenant_id", "tenant_id"),
        Index("idx_interview_questions_target_position", "target_position"),
        Index("idx_interview_questions_difficulty", "difficulty"),
        {"comment": "面试题库"},
    )

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("uuid_generate_v4()"),
        comment="主键（UUID）",
    )
    tenant_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, comment="租户ID（隔离边界，BigInteger）"
    )
    content: Mapped[str] = mapped_column(Text, nullable=False, comment="题目内容")
    difficulty: Mapped[str] = mapped_column(
        String(8), nullable=False, default="medium", comment="难度（easy/medium/hard）"
    )
    tags: Mapped[dict] = mapped_column(JSON, nullable=False, default=list, comment="标签（JSON）")
    target_position: Mapped[str] = mapped_column(
        String(128), nullable=False, default="general", comment="目标岗位"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, comment="是否启用"
    )
    created_user_id: Mapped[int] = mapped_column(
        BigInteger, comment="创建人ID（user_id，BigInteger）"
    )


class InterviewSession(AuditMixin, Base):
    """模拟面试会话。"""

    __tablename__ = "agent_interview_sessions"
    __table_args__ = (
        UniqueConstraint("thread_id", name="uq_interview_sessions_thread"),
        Index("idx_interview_sessions_tenant_id", "tenant_id"),
        Index("idx_interview_sessions_user_id", "user_id"),
        {"comment": "模拟面试会话"},
    )

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("uuid_generate_v4()"),
        comment="主键（UUID）",
    )
    tenant_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, comment="租户ID（隔离边界，BigInteger）"
    )
    user_id: Mapped[int] = mapped_column(BigInteger, comment="用户ID（user_id，BigInteger）")
    session_id: Mapped[str] = mapped_column(String(128), nullable=False, comment="会话标识")
    thread_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), nullable=False, comment="关联 agent_thread.id（会话）"
    )
    target_position: Mapped[str] = mapped_column(
        String(128), nullable=False, default="", comment="目标岗位"
    )
    resume_review_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), nullable=True, comment="关联简历审查ID（可选）"
    )
    summary: Mapped[str | None] = mapped_column(Text, nullable=True, comment="摘要")
    report: Mapped[dict | None] = mapped_column(JSON, nullable=True, comment="面试报告（JSON）")
    overall_score: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="综合得分")
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="in_progress",
        comment="状态（in_progress/finished/failed）",
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, comment="结束时间"
    )


# ------------------------- 问答结果（RAGAS 质量验证） -------------------------
class QaResult(AuditMixin, Base):
    """问答结果（一次问答一行，供 RAGAS 质量验证）。"""

    __tablename__ = "agent_qa_results"
    __table_args__ = (
        Index("idx_qa_results_tenant_time", "tenant_id", "create_at"),
        Index("idx_qa_results_user_time", "user_id", "create_at"),
        Index("idx_qa_results_session", "session_id"),
        Index("idx_qa_results_thread", "thread_id"),
        Index("idx_qa_results_trace", "trace_id"),
        Index("idx_qa_results_status", "status"),
        {"comment": "问答结果（一次问答一行，供 RAGAS 质量验证）"},
    )

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("uuid_generate_v4()"),
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
    session_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        comment="会话标识（qa 的 session_id / agent_thread.session_key）",
    )
    thread_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), nullable=True, comment="关联 agent_thread.id（会话）"
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
        server_default=text("uuid_generate_v4()"),
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
