"""ExamAgent：试卷批改 Agent 定义。"""

from __future__ import annotations

from typing import Any, Optional

from backend.agents.base import Agent
from backend.agents.exam.graph import build_exam_graph
from backend.orchestration.agent_spec import AgentSpec
from backend.orchestration.unified_schemas import AgentCard, EntryField, EntryFieldType
from backend.security.rbac import Scope


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

    def metadata(self) -> AgentSpec:
        return AgentSpec(
            agent_type="exam",
            display_name="智能出题",
            description="根据考纲/知识点智能生成试卷，支持 HITL 复核",
            intent_labels=("考试", "试卷", "出题", "exam"),
            intent_examples=("给我出一套数据结构试卷", "生成 Python 中级考题"),
            intent_hint="组卷/出题类诉求路由到考试",
            scope=Scope.EXAM_UPLOAD,
            card=AgentCard(icon="file", badge="任务", sort_order=3, action_label="创建试卷"),
            templates=("给我出一套数据结构试卷",),
            entry_fields=(
                EntryField(name="exam_id", label="试卷ID", type=EntryFieldType.STR, required=True),
            ),
            accept_files=(".docx",),
            execution_mode="task",
            checkpoint_scope=False,
            tags=("exam",),
            trace_name="unified.exam",
        )
