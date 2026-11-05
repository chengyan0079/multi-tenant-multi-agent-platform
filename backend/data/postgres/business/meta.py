"""
业务元数据表（业务域：知识库待补充、试卷批改、简历审查、模拟面试、问答）。

字段结构设计遵循本平台框架：
- id 统一 UUID（server_default=uuid_generate_v4()）
- 每张表继承 AuditMixin（create_at/updated_at/create_user_id/update_user_id/create_tenant_id/update_tenant_id）
- tenant_id VARCHAR(64) 隔离（用户以登录 token 里的 user_id 标识）
- 跨表引用（exam_id/question_id/submission_id/user_id/thread_id 等）用普通 UUID/VARCHAR 列 + 索引，
  不加外键约束，与核心 agent 表（thread_id/run_id）风格一致
- JSON 列用 JSON（与现有 agent_api_call_log.req_headers 一致）
"""
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
        UUID(as_uuid=False), primary_key=True, server_default=text("uuid_generate_v4()"), comment="主键（UUID）"
    )
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="租户ID（隔离边界，BigInteger）")
    question: Mapped[str] = mapped_column(Text, nullable=False, comment="待补充问题")
    user_id: Mapped[int] = mapped_column(BigInteger, comment="提交用户ID（user_id，BigInteger）")
    confidence: Mapped[float] = mapped_column(Float, nullable=False, comment="置信度")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", comment="状态（pending/resolved/dismissed）")
    resolved_user_id: Mapped[int] = mapped_column(BigInteger, comment="处理人ID（user_id，BigInteger）")
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
        UUID(as_uuid=False), primary_key=True, server_default=text("uuid_generate_v4()"), comment="主键（UUID）"
    )
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="租户ID（隔离边界，BigInteger）")
    title: Mapped[str] = mapped_column(String(256), nullable=False, comment="标题")
    description: Mapped[str] = mapped_column(Text, comment="描述")
    due_date: Mapped[datetime] = mapped_column(DateTime, comment="截止时间")
    created_user_id: Mapped[int] = mapped_column(BigInteger, comment="创建人ID（user_id，BigInteger）")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, comment="是否启用")


class Question(AuditMixin, Base):
    """试卷题目。"""

    __tablename__ = "agent_questions"
    __table_args__ = (
        Index("idx_questions_exam_id", "exam_id"),
        Index("idx_questions_knowledge_tag", "knowledge_tag"),
        {"comment": "试卷题目"},
    )

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, server_default=text("uuid_generate_v4()"), comment="主键（UUID）"
    )
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="租户ID（隔离边界，BigInteger）")
    exam_id: Mapped[str] = mapped_column(UUID(as_uuid=False), comment="所属试卷ID")
    question_no: Mapped[int] = mapped_column(Integer, nullable=False, comment="题号")
    question_type: Mapped[str] = mapped_column(
        String(16), nullable=False, comment="题型（single_choice/multi_choice/judge/short_answer/code）"
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
        UUID(as_uuid=False), primary_key=True, server_default=text("uuid_generate_v4()"), comment="主键（UUID）"
    )
    question_id: Mapped[str] = mapped_column(UUID(as_uuid=False), comment="题目ID")
    point_desc: Mapped[str] = mapped_column(Text, nullable=False, comment="评分点描述")
    point_score: Mapped[int] = mapped_column(Integer, nullable=False, comment="评分点分值")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, comment="是否启用")
    confirmed_user_id: Mapped[int] = mapped_column(BigInteger, comment="确认人ID（user_id，BigInteger）")
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
        UUID(as_uuid=False), primary_key=True, server_default=text("uuid_generate_v4()"), comment="主键（UUID）"
    )
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="租户ID（隔离边界，BigInteger）")
    exam_id: Mapped[str] = mapped_column(UUID(as_uuid=False), comment="试卷ID")
    user_id: Mapped[int] = mapped_column(BigInteger, comment="用户ID（user_id，BigInteger）")
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="word", comment="来源（word/online/miniapp）")
    word_minio_path: Mapped[str] = mapped_column(String(512), comment="Word 文件 MinIO 路径")
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="submitted",
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
        UUID(as_uuid=False), primary_key=True, server_default=text("uuid_generate_v4()"), comment="主键（UUID）"
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
    needs_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, comment="是否需要人工复核")
    reviewed_user_id: Mapped[int] = mapped_column(BigInteger, comment="复核人ID（user_id，BigInteger）")
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
        UUID(as_uuid=False), primary_key=True, server_default=text("uuid_generate_v4()"), comment="主键（UUID）"
    )
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="租户ID（隔离边界，BigInteger）")
    user_id: Mapped[int] = mapped_column(BigInteger, comment="用户ID（user_id，BigInteger）")
    pdf_minio_path: Mapped[str] = mapped_column(String(512), nullable=False, comment="PDF 文件 MinIO 路径")
    weighted_score: Mapped[float] = mapped_column(
        Numeric(5, 2), default=0.0, comment="综合加权得分（0-100，由六维度加权计算）"
    )
    structured_data: Mapped[dict | None] = mapped_column(JSON, nullable=True, comment="结构化信息（JSON，上传时为空）")
    scores: Mapped[dict | None] = mapped_column(JSON, nullable=True, comment="评分（JSON）")
    issues: Mapped[dict | None] = mapped_column(JSON, nullable=True, comment="问题清单（JSON）")
    summary: Mapped[dict | None] = mapped_column(JSON, nullable=True, comment="摘要（JSON）")
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", comment="状态（pending/processing/done/failed）"
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
        UUID(as_uuid=False), primary_key=True, server_default=text("uuid_generate_v4()"), comment="主键（UUID）"
    )
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="租户ID（隔离边界，BigInteger）")
    content: Mapped[str] = mapped_column(Text, nullable=False, comment="题目内容")
    difficulty: Mapped[str] = mapped_column(String(8), nullable=False, default="medium", comment="难度（easy/medium/hard）")
    tags: Mapped[dict] = mapped_column(JSON, nullable=False, default=list, comment="标签（JSON）")
    target_position: Mapped[str] = mapped_column(String(128), nullable=False, default="general", comment="目标岗位")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, comment="是否启用")
    created_user_id: Mapped[int] = mapped_column(BigInteger, comment="创建人ID（user_id，BigInteger）")


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
        UUID(as_uuid=False), primary_key=True, server_default=text("uuid_generate_v4()"), comment="主键（UUID）"
    )
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="租户ID（隔离边界，BigInteger）")
    user_id: Mapped[int] = mapped_column(BigInteger, comment="用户ID（user_id，BigInteger）")
    session_id: Mapped[str] = mapped_column(String(128), nullable=False, comment="会话标识")
    thread_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False, comment="关联 agent_thread.id（会话）")
    target_position: Mapped[str] = mapped_column(String(128), nullable=False, default="", comment="目标岗位")
    resume_review_id: Mapped[str] = mapped_column(UUID(as_uuid=False), comment="关联简历审查ID")
    summary: Mapped[str] = mapped_column(Text, comment="摘要")
    report: Mapped[dict] = mapped_column(JSON, comment="面试报告（JSON）")
    overall_score: Mapped[int] = mapped_column(Integer, comment="综合得分")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="in_progress", comment="状态（in_progress/finished）")
    finished_at: Mapped[datetime] = mapped_column(DateTime, comment="结束时间")


# ------------------------- 问答会话 -------------------------
class QaSession(AuditMixin, Base):
    """问答会话（关联 agent_thread）。"""

    __tablename__ = "agent_qa_sessions"
    __table_args__ = (
        UniqueConstraint("thread_id", name="uq_qa_sessions_thread"),
        Index("idx_qa_sessions_tenant_id", "tenant_id"),
        Index("idx_qa_sessions_user_id", "user_id"),
        {"comment": "问答会话"},
    )

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, server_default=text("uuid_generate_v4()"), comment="主键（UUID）"
    )
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="租户ID（隔离边界，BigInteger）")
    user_id: Mapped[int] = mapped_column(BigInteger, comment="用户ID（user_id，BigInteger）")
    thread_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False, comment="关联 agent_thread.id（会话）")
    summary: Mapped[str] = mapped_column(Text, comment="摘要")
    summary_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="摘要版本")
