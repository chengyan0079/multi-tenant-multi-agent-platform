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

    messages: Annotated[list[BaseMessage], add_messages]  # 消息历史（多轮合并）
    user_id: int  # 用户 id
    tenant_id: int  # 租户 id
    thread_id: str  # checkpointer 分区键
    session_id: str  # 业务会话标识
    target_position: str  # 目标岗位

    # 简历联动（可选）
    resume_review_id: Optional[str]  # 关联简历评审 id
    resume_projects: list[dict]  # 简历项目
    resume_skills: list[str]  # 简历技能

    # 阶段控制
    current_stage: str  # 当前阶段
    stage_turn_count: int  # 本阶段轮数
    total_turn_count: int  # 总轮数
    max_turns: int  # 轮数上限

    # 题目管理
    question_bank: list[dict]  # 题库
    current_question: Optional[dict]  # 当前问题
    projects_asked: list[str]  # 已追问项目

    # 回答质量
    last_answer_quality: str  # 上一回答质量
    followup_count: int  # 连续追问次数

    # 摘要与报告
    existing_summary: Optional[str]  # 会话摘要
    should_summarize: bool  # 是否触发摘要
    report: Optional[dict]  # 面试报告
    fallback_used: bool  # 是否走了兜底
    structured_output: Optional[dict]  # 结构化输出
