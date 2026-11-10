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
                "thread_id": {"type": "string"},
                "target_position": {"type": "string"},
                "candidate_answer": {"type": "string"},
                "resume_review_id": {"type": ["string", "null"]},
                "tenant_id": {"type": "integer"},
                "user_id": {"type": "integer"},
            },
            "required": ["session_id", "target_position"],
        }

    def metadata(self) -> Dict[str, Any]:
        return {
            "description": "模拟面试：阶段推进→回答评估→面试官回应→报告",
            "pattern": "state-machine + checkpointer + sse",
            "capabilities": [
                "interview_question_bank",
                "interview_evaluator",
                "interviewer_persona",
            ],
        }
