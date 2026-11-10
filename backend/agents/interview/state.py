"""模拟面试 Agent 状态定义：thread_id 为 checkpointer key，session_id 为业务会话标识。"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Optional

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field
from typing_extensions import TypedDict


class InterviewStage(StrEnum):
    """面试阶段。"""

    WARMUP = "warmup"
    TECH_BASE = "tech_base"
    PROJECT = "project"
    CLOSING = "closing"
    FINISHED = "finished"


class AnswerQuality(StrEnum):
    """单次回答质量，驱动追问/换题。"""

    EXCELLENT = "excellent"
    ADEQUATE = "adequate"
    WEAK = "weak"
    NO_ANSWER = "no_answer"


class DimensionEval(BaseModel):
    """单个维度评估结果。"""

    dimension: str = Field(description="评估维度名称")
    score: int = Field(description="得分 0-100")
    comment: str = Field(description="1-2 句评语")
    highlights: list[str] = Field(default_factory=list, description="亮点")
    weaknesses: list[str] = Field(default_factory=list, description="薄弱点")


class InterviewReport(BaseModel):
    """五维度面试报告。"""

    dimensions: list[DimensionEval]
    overall_score: int = Field(description="综合得分 0-100")
    strengths: list[str] = Field(description="核心优势")
    improvements: list[str] = Field(description="重点提升方向")
    overall_comment: str = Field(description="综合评语")
    recommended_topics: list[str] = Field(description="建议复习的知识点")
    next_step_advice: str = Field(description="下一步备考建议")


class InterviewState(TypedDict):
    """模拟面试完整 State。"""

    messages: Annotated[list[BaseMessage], add_messages]
    user_id: int
    tenant_id: int
    thread_id: str
    session_id: str
    target_position: str

    # 简历联动（可选）
    resume_review_id: Optional[str]
    resume_projects: list[dict]
    resume_skills: list[str]

    # 阶段控制
    current_stage: str
    stage_turn_count: int
    total_turn_count: int
    max_turns: int

    # 题目管理
    question_bank: list[dict]
    current_question: Optional[dict]
    projects_asked: list[str]

    # 回答质量
    last_answer_quality: str
    followup_count: int

    # 摘要与报告
    existing_summary: Optional[str]
    should_summarize: bool
    report: Optional[dict]
    fallback_used: bool
    structured_output: Optional[dict]
