"""ExamAgent：试卷批改 Agent 定义。"""

from __future__ import annotations

from typing import Any, Dict, Optional

from backend.agents.base import Agent
from backend.agents.exam.graph import build_exam_graph


class ExamAgent(Agent):
    agent_type = "exam"

    def build_graph(self) -> Any:
        return build_exam_graph()

    def input_schema(self) -> Optional[dict]:
        return {
            "type": "object",
            "properties": {
                "file_ref": {"type": "string"},
                "tenant_id": {"type": "string"},
            },
            "required": ["file_ref"],
        }

    def metadata(self) -> Dict[str, Any]:
        return {
            "description": "试卷批改：解析→三轨并行→汇总→HITL→教师确认发布",
            "pattern": "parallel + hitl",
            "capabilities": ["word_parse", "objective_grader", "subjective_rubric", "code_exec"],
        }
