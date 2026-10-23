"""
业务元数据表示例（骨架占位）。

每个 Agent 的专属元数据按 EduAgent 规范独立建表，与核心表共用同一 PostgreSQL、按 tenant_id 隔离。
此处给出简历/批改/面试三类代表表，问答复用 rag-ultra 知识库不在此落地。
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.orm_models.base import Base


class ResumeRecord(Base):
    """简历审查结果（人才库/评分配置/报告模板按租户隔离）。"""

    __tablename__ = "biz_resume_record"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    file_ref: Mapped[str] = mapped_column(String(128), default="")
    scores: Mapped[str] = mapped_column(Text, default="{}")  # JSON 六维度
    report: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ExamRecord(Base):
    """试卷批改结果（题库/答卷/判分规则按租户隔离）。"""

    __tablename__ = "biz_exam_record"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    file_ref: Mapped[str] = mapped_column(String(128), default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    published: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class InterviewRecord(Base):
    """面试报告（题库/人设/报告按租户隔离）。"""

    __tablename__ = "biz_interview_record"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    session_id: Mapped[str] = mapped_column(String(64), default="")
    report: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
