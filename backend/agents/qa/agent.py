"""QAAgent：智能问答 Agent 定义。"""

from __future__ import annotations

from typing import Any, Dict, Optional

from backend.agents.base import Agent
from backend.agents.qa.graph import build_qa_graph


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

    def metadata(self) -> Dict[str, Any]:
        return {
            "description": "智能问答：意图分类→检索(RAG)→生成→低置信Web兜底，支持多轮与历史摘要",
            "pattern": "rag",
            "capabilities": ["rag_retrieval", "web_search", "hyde", "multi_query", "summary"],
        }
