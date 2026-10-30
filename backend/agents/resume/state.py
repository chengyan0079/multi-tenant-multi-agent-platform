"""
state - 简历评审相关数据结构

"""
import operator
from typing import Annotated

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field
from typing_extensions import TypedDict


class EducationItem(BaseModel):
    """单条教育经历"""
    school: str = Field(description='学校名称')
    major: str = Field(description='专业名称')
    degree: str = Field(description='学历：本科/专科/硕士等')
    duration: str = Field(description='在校时间，如 2020.09 - 2024.06')
    gpa: str = Field(default='', description='GPA 或成绩（可选）')


class ProjectItem(BaseModel):
    """单条项目经历"""
    name: str = Field(description='项目名称')
    role: str = Field(description='担任角色，如：后端开发/全栈/负责人')
    duration: str = Field(description='项目时间，如 2023.06 - 2023.12')
    tech_stack: list[str] = Field(description='使用的技术栈列表，如 [Spring Boot, MySQL, Redis]')
    description: str = Field(description='项目描述原文（保留原始表述）')
    highlights: list[str] = Field(default_factory=list, description='量化亮点句子列表（含数字的句子）')


class WorkItem(BaseModel):
    """单条工作/实习经历"""
    company: str = Field(description='公司名称')
    position: str = Field(description='职位名称')
    duration: str = Field(description='工作时间')
    tech_stack: list[str] = Field(default_factory=list, description='涉及技术栈')
    description: str = Field(description='工作内容原文')


class ResumeStructured(BaseModel):
    """简历结构化提取结果"""
    # 基本信息
    name: str = Field(description='姓名')
    phone: str = Field(default='', description='手机号')
    email: str = Field(default='', description='邮箱')
    target_position: str = Field(default='', description='求职意向岗位')

    # 教育经历（时间倒序）
    education: list[EducationItem] = Field(default_factory=list)

    # 技能
    skills_raw: str = Field(default='', description='技能栏原始文本')
    skills_list: list[str] = Field(default_factory=list, description='解析后的技术标签列表')

    # 项目经历
    projects: list[ProjectItem] = Field(default_factory=list)

    # 工作/实习经历
    work_experience: list[WorkItem] = Field(default_factory=list)

    # 其他
    certificates: list[str] = Field(default_factory=list, description='证书列表')
    self_intro: str = Field(default='', description='个人简介/自我评价原文')


class DimensionScore(BaseModel):
    """单个评审维度结果"""
    dimension: str = Field(default='', description='考察维度的名称')
    weight: float = Field(default=0.0, description='权重')
    score: int = Field(description='得分', ge=0, le=100)
    issues: list[str] = Field(default_factory=list, description='该维度问题的列表')
    suggestions: list[str] = Field(default_factory=list, description='改进建议的列表')


class IssueItem(BaseModel):
    """单条诊断问题。"""
    priority: str = Field(description='优先级：high / medium / low')
    dimension: str = Field(description='所属维度')
    description: str = Field(description='问题描述（1句话）')
    location: str = Field(description='问题在简历中的定位，如：项目经历-电商系统-第2句')
    suggestion: str = Field(description='具体修改建议（可操作）')


class IssueList(BaseModel):
    """IssueItem 列表"""
    items: list[IssueItem]


class ResumeSummary(BaseModel):
    """简历整体评价"""
    highlights: list[str] = Field(description='2-3 条核心亮点')
    core_improvements: list[str] = Field(description='2-3 条最重要的改进方向')
    overall_comment: str = Field(description='1-2 句综合评语')
    fit_assessment: str = Field(description='对目标岗位的匹配度评估（1句话）')


class ResumeState(TypedDict, total=False):
    """简历审查 Agent 完整 State"""
    messages: Annotated[list[BaseMessage], add_messages]

    # 对应工作流的①和②节点
    student_id: str
    tenant_id: str
    review_id: str       # 简历评审的流水号 - UUID
    pdf_minio_path: str  # 简历文件保存路径（云存储的 URI 或分布式文件系统标识符）
    pdf_local_path: str

    # 解析中间结果（对应工作流的③节点）
    raw_text: str
    page_count: int

    # 结构化提取结果（对应工作流的④节点）
    structured: ResumeStructured | None

    # 六维度评审结果（对应工作流的⑤节点）
    dimension_scores: Annotated[list[DimensionScore], operator.add]
    weighted_score: float

    # 逐条问题诊断（对应工作流的⑥节点）
    issues: Annotated[list[IssueItem], operator.add]

    # 整体评价（对应工作流的⑦节点）
    summary: ResumeSummary | None

    # 降级标记
    fallback_used: bool
    structured_output: dict | None
