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
                "query": {"type": "string"},
                "tenant_id": {"type": "string"},
            },
            "required": ["query"],
        }

    def metadata(self) -> Dict[str, Any]:
        return {
            "description": "智能问答：意图分类→检索(rag-ultra)→生成→低置信Web兜底",
            "pattern": "rag",
            "capabilities": ["rag_retrieve", "web_search"],
        }
