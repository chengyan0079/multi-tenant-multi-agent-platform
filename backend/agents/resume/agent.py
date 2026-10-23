"""ResumeAgent：简历审查 Agent 定义（继承基类）。"""
from __future__ import annotations

from typing import Any, Dict, Optional

from backend.agents.base import Agent
from backend.agents.resume.graph import build_resume_graph


class ResumeAgent(Agent):
    agent_type = "resume"

    def build_graph(self) -> Any:
        return build_resume_graph()

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
            "description": "简历审查：PDF 解析→六维度并行评分→诊断→报告",
            "pattern": "fan-out/fan-in",
            "capabilities": ["pdf_parse", "resume_scorer_*"],
        }
