"""QAAgent：智能问答 Agent 定义。"""

from __future__ import annotations

from typing import Any

from backend.agents.base import Agent
from backend.agents.qa.graph import build_qa_graph
from backend.orchestration.agent_spec import AgentSpec
from backend.orchestration.unified_schemas import AgentCard
from backend.security.rbac import Scope


class QAAgent(Agent):
    agent_type = "qa"

    def build_graph(self) -> Any:
        return build_qa_graph()

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
            display_name="智能问答",
            description="意图分类→检索(RAG)→生成→低置信Web兜底，支持多轮与历史摘要",
            intent_labels=("问答", "智能问答", "知识查询", "qa"),
            intent_examples=("怎么用 LangGraph 做检查点？", "帮我查一下简历优化建议"),
            intent_hint="通用知识/检索类问题优先路由到问答",
            default_agent=True,
            scope=Scope.QA_ASK,
            card=AgentCard(icon="chat", badge="常用", sort_order=1, action_label="开始问答"),
            templates=("怎么用 LangGraph 做检查点？", "解释一下 RAG 的召回策略"),
            execution_mode="stream",
            checkpoint_scope=False,  # 每轮独立分区
            generate_nodes=("generate",),
            tags=("qa",),
            trace_name="unified.qa",
        )
