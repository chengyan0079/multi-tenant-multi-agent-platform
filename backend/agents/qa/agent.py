"""QAAgent：智能问答 Agent 定义（基于 AgentTemplate 模板装配）。"""

from __future__ import annotations

from typing import Optional

from backend.agents.qa.graph import (
    _route_after_web_search,
    _route_by_confidence,
    _route_by_query_type,
)
from backend.agents.qa.nodes import (
    classify_query_node,
    enqueue_pending_node,
    generate_direct_node,
    generate_general_node,
    generate_rag_node,
    hyde_generate_node,
    multi_query_rewrite_node,
    retrieve_node,
    save_memory_node,
    web_search_node,
)
from backend.agents.qa.state import QAState
from backend.agents.template import AgentTemplate, FlowSpec
from backend.orchestration.agent_spec import AgentSpec
from backend.orchestration.unified_schemas import AgentCard
from backend.security.rbac import Scope


class QAAgent(AgentTemplate):
    agent_type = "qa"
    state_cls = QAState

    def flow(self) -> FlowSpec:
        return FlowSpec(
            nodes={
                "classify_query": classify_query_node,
                "hyde_generate": hyde_generate_node,
                "multi_query_rewrite": multi_query_rewrite_node,
                "retrieve": retrieve_node,
                "generate_rag": generate_rag_node,
                "web_search": web_search_node,
                "generate_direct": generate_direct_node,
                "generate_general": generate_general_node,
                "enqueue_pending": enqueue_pending_node,
                "save_memory": save_memory_node,
            },
            entry="classify_query",
            edges=[
                ("hyde_generate", "retrieve"),
                ("multi_query_rewrite", "retrieve"),
                ("generate_rag", "save_memory"),
                ("generate_general", "save_memory"),
                ("generate_direct", "enqueue_pending"),
                ("enqueue_pending", "save_memory"),
            ],
            conditional=[
                (
                    "classify_query",
                    _route_by_query_type,
                    {
                        "GENERAL": "generate_general",
                        "GENERAL_WEB": "web_search",
                        "PRECISE": "retrieve",
                        "VAGUE": "hyde_generate",
                        "BROAD": "multi_query_rewrite",
                    },
                ),
                (
                    "retrieve",
                    _route_by_confidence,
                    {
                        "high": "generate_rag",
                        "low_web": "web_search",
                        "low_direct": "generate_direct",
                    },
                ),
                (
                    "web_search",
                    _route_after_web_search,
                    {
                        "generate_general": "generate_general",
                        "generate_direct": "generate_direct",
                    },
                ),
            ],
            end_nodes=["save_memory"],
        )

    def input_schema(self) -> Optional[dict]:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "用户提问内容"},
                "tenant_id": {"type": "integer", "description": "租户 ID（多租户隔离）"},
                "user_id": {"type": "integer", "description": "用户 ID"},
                "session_id": {
                    "type": "string",
                    "description": "会话 ID（可选，用于构造 thread_id）",
                },
            },
            "required": ["query", "tenant_id", "user_id"],
        }

    def metadata(self) -> AgentSpec:
        return AgentSpec(
            agent_type="qa",
            display_name="知识问答",
            description=(
                "基于知识库的检索增强问答（RAG）：规范、流程、技术资料、产品文档等多领域问题；"
                "支持混合检索 + 精排、低置信度 Web 兜底、多轮对话与历史摘要"
            ),
            intent_labels=("问答", "知识问答", "知识查询", "资料检索", "qa"),
            intent_examples=(
                "大表加字段怎么做才不锁表？",
                "变更发布流程有哪些审批环节？",
                "这个报错一般是什么原因？",
            ),
            intent_hint=(
                "知识/资料/规范/流程/原理类问题优先路由到问答（覆盖面最广，作为默认兜底）；"
                "仅当用户明确要求评审某条 SQL 的风险时才走变更评审，要求沙箱验证/放行走变更发布"
            ),
            default_agent=True,
            scope=Scope.UNIFIED_ASK,
            card=AgentCard(icon="read", badge="常用", sort_order=1, action_label="开始问答"),
            templates=(
                "大表加字段怎么做才不锁表？",
                "变更发布流程有哪些审批环节？",
                "RAG 检索效果不好可以从哪些方面优化？",
            ),
            execution_mode="stream",
            checkpoint_scope=False,  # 每轮独立分区
            generate_nodes=("generate_rag", "generate_direct", "generate_general"),
            tags=("qa", "knowledge", "rag"),
            trace_name="unified.qa",
        )
