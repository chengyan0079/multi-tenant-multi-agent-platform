"""智能问答状态定义。

与参考项目 agents/qa/state.py 结构保持一致（total=False TypedDict），仅把 tenant_id
改为 int 以贴合本项目的租户 id 类型；额外保留可选 query 字段，兼容统一聊天入口直接传
query（而非 messages）的调用方式。
"""
from __future__ import annotations

from typing import Annotated, Optional

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict


class QAState(TypedDict, total=False):
    """智能问答 Agent 的状态定义。"""

    # 消息历史（LangGraph 用 add_messages 做增量合并，支撑多轮）
    messages: Annotated[list[BaseMessage], add_messages]

    # 请求上下文
    user_id: int
    tenant_id: int
    session_id: str
    query: str  # 统一聊天入口的 query 透传；classify 优先读 messages

    # Query 处理中间结果
    original_query: str
    query_type: str  # GENERAL / PRECISE / VAGUE / BROAD
    rewritten_queries: list[str]
    hyde_document: Optional[str]

    # 检索与精排结果
    ranked_chunks: list[dict]
    confidence: float
    is_high_confidence: bool
    web_search_results: list[dict]

    # 生成结果与控制标记
    answer: str
    sources: list[str]
    answer_mode: str  # 'rag' / 'llm_direct' / 'web_augmented' / 'general'
    existing_summary: Optional[str]
    should_summarize: bool
    enable_web_search: bool

    fallback_used: bool
    structured_output: Optional[dict]
