"""InterviewAgent：模拟面试 Agent 定义。"""

from __future__ import annotations

from typing import Any

from backend.agents.base import Agent
from backend.agents.interview.graph import build_interview_graph
from backend.orchestration.agent_spec import AgentSpec
from backend.orchestration.unified_schemas import (
    AgentCard,
    EntryField,
    EntryFieldType,
    ProgressLabel,
)
from backend.security.rbac import Scope


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

    def metadata(self) -> AgentSpec:
        return AgentSpec(
            agent_type="interview",
            display_name="模拟面试",
            description="模拟面试：阶段推进→回答评估→面试官回应→报告",
            intent_labels=("面试", "模拟面试", "求职面试", "interview"),
            intent_examples=("我想练习后端面试", "来一场 Java 面试"),
            intent_hint="求职/面试练习类诉求路由到面试",
            scope=Scope.INTERVIEW_ASK,
            card=AgentCard(icon="user", badge="进阶", sort_order=2, action_label="开始面试"),
            templates=("我想练习后端面试", "来一场 Java 面试"),
            entry_fields=(
                EntryField(name="target_position", label="目标岗位", type=EntryFieldType.STR, required=True),
                EntryField(name="resume_review_id", label="简历ID", type=EntryFieldType.STR, required=False),
            ),
            execution_mode="stream",
            checkpoint_scope=True,  # 按面试实例固定分区
            progress_labels=(
                ProgressLabel(node="ask_question", text="出题"),
                ProgressLabel(node="evaluate", text="评估"),
            ),
            generate_nodes=("ask_question", "evaluate", "interviewer_reply"),
            tags=("interview",),
            trace_name="unified.interview",
        )
