"""试卷批阅状态结构（BaseModel + TypedDict，对齐 resume/state 范式）。"""

from typing import Annotated, Optional

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field
from typing_extensions import TypedDict


class ScoringPointItem(BaseModel):
    """数据库得分点（标准答案拆解，用于简答题预填）"""

    id: str = Field(default="", description="得分点 ID")
    desc: str = Field(default="", description="得分点描述")
    score: int = Field(default=0, description="该得分点满分")


class ParsedQuestion(BaseModel):
    """合并后的单题（题目元数据 + 学员作答）"""

    question_id: str = Field(default="", description="题目 ID")
    question_no: int = Field(default=0, description="题号")
    question_type: str = Field(default="", description="题型")
    content: str = Field(default="", description="题目内容")
    student_answer: str = Field(default="", description="学员作答")
    correct_answer: str = Field(default="", description="标准答案")
    scoring_points: list[ScoringPointItem] = Field(default_factory=list, description="得分点列表")
    full_score: int = Field(default=0, description="满分")
    knowledge_tag: str = Field(default="", description="知识点标签")
    is_code: bool = Field(default=False, description="解析期判定是否为代码题")


class ScoringPointResult(BaseModel):
    """单个得分点评分结果"""

    point_id: str = Field(description="得分点 ID（来自 scoring_points 表）")
    point_desc: str = Field(description="得分点描述")
    point_score: int = Field(description="该得分点满分")
    earned: bool = Field(description="是否得分")
    evidence: str = Field(default="", description="得分时支撑该得分点的原文")
    missing: str = Field(default="", description="失分时缺失/错误的具体原因")


class SubjectiveReviewResult(BaseModel):
    """简答题批改结果"""

    question_id: str = Field(description="题目 ID")
    student_answer: str = Field(description="学员答案（原样回显）")
    total_score: int = Field(description="本题得分")
    full_score: int = Field(description="本题满分")
    confidence: float = Field(description="评分把握度 0~1")
    point_results: list[ScoringPointResult] = Field(
        default_factory=list, description="逐得分点明细"
    )
    overall_comment: str = Field(default="", description="整体评语")


class WeakPoint(BaseModel):
    """单个知识薄弱点"""

    tag: str = Field(description="知识点标签")
    wrong_count: int = Field(description="答错/扣分题数")
    total_count: int = Field(description="涉及题数")
    question_nos: list[int] = Field(default_factory=list, description="涉及题号")
    suggestion: str = Field(default="", description="复习建议")


class WeakPointsReport(BaseModel):
    """知识薄弱点分析报告"""

    weak_points: list[WeakPoint] = Field(default_factory=list)
    overall_summary: str = Field(default="", description="整体表现评价")


class Modification(BaseModel):
    """教师修改项"""

    question_id: str = Field(description="题目 ID")
    new_score: Optional[int] = Field(default=None, description="修改后的得分")
    comment: Optional[str] = Field(default=None, description="教师评语")


class TeacherDecision(BaseModel):
    """教师确认决策"""

    action: str = Field(description='"approve" / "modify"')
    modifications: list[Modification] = Field(default_factory=list, description="修改项列表")
    teacher_id: str = Field(default="", description="教师 ID")


class ByQuestionItem(BaseModel):
    """逐题批改结果（三轨合并后的统一结构，也是发布单元）"""

    question_id: str = Field(default="", description="题目 ID")
    question_no: int = Field(default=0, description="题号")
    question_type: str = Field(default="", description="题型")
    knowledge_tag: str = Field(default="", description="知识点标签")
    content: str = Field(default="", description="题目内容")
    student_answer: str = Field(default="", description="学员答案")
    correct_answer: str = Field(default="", description="标准答案")
    is_correct: bool = Field(default=False, description="客观题是否正确")
    score: int = Field(default=0, description="AI 得分")
    full_score: int = Field(default=0, description="满分")
    needs_review: bool = Field(default=False, description="是否需教师复核")
    ai_feedback: str = Field(default="", description="AI 评语")
    confidence: float = Field(default=0.0, description="评分把握度")
    point_results: list[ScoringPointResult] = Field(default_factory=list, description="得分点明细")
    quality_feedback: list[str] = Field(default_factory=list, description="代码质量评语")
    teacher_score: Optional[int] = Field(default=None, description="教师得分")
    teacher_comment: str = Field(default="", description="教师评语")
    final_score: int = Field(default=0, description="最终得分")


class PreReviewSummary(BaseModel):
    """预批改汇总"""

    total_score: int = Field(default=0, description="总分")
    full_score: int = Field(default=0, description="总满分")
    score_rate: float = Field(default=0.0, description="得分率")
    needs_review_count: int = Field(default=0, description="需复核题数")
    by_question: list[ByQuestionItem] = Field(default_factory=list, description="逐题结果")


class ExamState(TypedDict, total=False):
    """试卷批改工作流全局状态"""

    messages: Annotated[list[BaseMessage], add_messages]

    # 请求上下文
    student_id: str  # 学员 ID
    tenant_id: str  # 租户 ID
    session_id: str  # 会话 ID
    exam_id: str  # 试卷 ID
    submission_id: str  # 提交记录 ID（更新状态/写批改结果用）
    word_minio_path: str  # 学员作答 Word 的 MinIO key

    # 合并后的完整题目列表
    parsed_questions: list[ParsedQuestion]

    # 三轨批改结果（统一为 ByQuestionItem）
    objective_results: list[ByQuestionItem]  # 第一轨：客观题规则批改
    subjective_results: list[ByQuestionItem]  # 第二轨：简答题语义评分
    code_results: list[ByQuestionItem]  # 第三轨：代码题评估

    # 汇总预批改结果
    pre_review_summary: PreReviewSummary | None

    # 知识薄弱点分析
    weak_points: list[WeakPoint]
    weak_points_summary: str

    # Human-in-the-Loop
    teacher_notified: bool
    teacher_decision: TeacherDecision | None

    # 最终结果
    final_results: list[ByQuestionItem]

    published: bool
    fallback_used: bool
    sandbox_skipped: bool
    structured_output: dict | None
