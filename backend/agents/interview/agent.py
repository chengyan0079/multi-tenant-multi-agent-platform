"""InterviewAgent：模拟面试 Agent 定义。"""
from __future__ import annotations

from typing import Any, Dict, Optional

from backend.agents.base import Agent
from backend.agents.interview.graph import build_interview_graph


class InterviewAgent(Agent):
    agent_type = "interview"

    def build_graph(self) -> Any:
        return build_interview_graph()

    def input_schema(self) -> Optional[dict]:
        return {
            "type": "object",
            "properties": {
                "session_id": {"type": "string"},
                "candidate_answer": {"type": "string"},
                "tenant_id": {"type": "string"},
            },
            "required": ["session_id"],
        }

    def metadata(self) -> Dict[str, Any]:
        return {
            "description": "模拟面试：状态机推进→质量评估→面试官回应→报告",
            "pattern": "state-machine + sse",
            "capabilities": ["interview_bank_retriever", "interview_evaluator", "interviewer_persona"],
        }
