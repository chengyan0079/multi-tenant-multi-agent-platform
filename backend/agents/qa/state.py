"""智能问答状态定义：total=False TypedDict，tenant_id 为 int，list 收敛为具体对象。"""

from __future__ import annotations

from typing import Annotated, Optional

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field
from typing_extensions import TypedDict


class RankedChunk(BaseModel):
    """知识库检索精排后的单条片段（父子片：content 为命中子片）。"""

    content: str = Field(default="", description="命中子片正文（精排输入）")
    score: float = Field(default=0.0, description="相似度得分")
    source: str = Field(default="", description="来源标识")
    doc_id: str = Field(default="", description="所属文档 ID")
    chunk_id: str = Field(default="", description="子片 ID")
    metadata: dict = Field(default_factory=dict, description="附加元数据")
    parent_id: str = Field(default="", description="所属父片 ID")
    parent_content: str = Field(default="", description="父片全文（small-to-big 上下文）")
    highlighted_content: str = Field(
        default="", description="父片内高亮命中子片的文本，供生成节点使用"
    )
    chunk_type: str = Field(default="child", description="块类型：child / parent")
    extra: dict = Field(default_factory=dict, description="额外元数据")


class WebSearchResult(BaseModel):
    """联网检索单条结果。"""

    url: str = Field(default="", description="链接")
    title: str = Field(default="", description="标题")
    snippet: str = Field(default="", description="摘要")


class QAState(TypedDict, total=False):
    """智能问答 Agent 的状态定义。"""

    # 消息历史（LangGraph 用 add_messages 做增量合并，支撑多轮）
    messages: Annotated[list[BaseMessage], add_messages]

    # 请求上下文
    user_id: int
    tenant_id: int
    # 思考模式（前端开关）：True 时 LLM 开启推理，流式输出思考过程
    thinking: bool
    session_id: str
    query: str  # 统一聊天入口的 query 透传；classify 优先读 messages

    # Query 处理中间结果
    original_query: str
    query_type: str  # GENERAL / PRECISE / VAGUE / BROAD
    rewritten_queries: list[str]
    hyde_document: Optional[str]

    # 检索与精排结果
    ranked_chunks: list[RankedChunk]
    confidence: float
    is_high_confidence: bool
    web_search_results: list[WebSearchResult]

    # 生成结果与控制标记
    answer: str
    sources: list[str]
    answer_mode: str  # 'rag' / 'llm_direct' / 'web_augmented' / 'general'
    existing_summary: Optional[str]
    should_summarize: bool
    enable_web_search: bool

    fallback_used: bool
    structured_output: Optional[dict]
