"""ResumeAgent：简历审查 Agent 定义（继承基类）。"""

from __future__ import annotations

from typing import Any

from backend.agents.base import Agent
from backend.agents.resume.graph import build_resume_graph
from backend.orchestration.agent_spec import AgentSpec
from backend.orchestration.unified_schemas import AgentCard
from backend.security.rbac import Scope


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

    def metadata(self) -> AgentSpec:
        return AgentSpec(
            agent_type="resume",
            display_name="简历分析",
            description="解析 PDF 简历，给出优化建议与岗位匹配度",
            intent_labels=("简历", "简历分析", "简历优化", "resume"),
            intent_examples=("帮我优化简历", "分析我的简历匹配度"),
            intent_hint="简历解析/优化类诉求路由到简历",
            scope=Scope.RESUME_UPLOAD,
            card=AgentCard(icon="document", badge="任务", sort_order=4, action_label="上传简历"),
            templates=("帮我优化简历",),
            accept_files=(".pdf",),
            execution_mode="task",
            checkpoint_scope=False,
            tags=("resume",),
            trace_name="unified.resume",
        )
