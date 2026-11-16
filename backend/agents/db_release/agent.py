"""DbReleaseAgent：数据库变更发布（沙箱验证 + 输出原样 SQL）。"""

from __future__ import annotations

from typing import Optional

from backend.agents.db_release.nodes import (
    guard_node,
    load_request_node,
    persist_node,
    save_memory_node,
    route_guard,
    route_load,
    shadow_execute_node,
    verify_node,
)
from backend.agents.db_release.state import DbReleaseState
from backend.agents.template import AgentTemplate, FlowSpec, hitl_node
from backend.orchestration.agent_spec import AgentSpec
from backend.orchestration.unified_schemas import AgentCard, EntryField, EntryFieldType
from backend.security.rbac import Scope


class DbReleaseAgent(AgentTemplate):
    agent_type = "db_release"
    state_cls = DbReleaseState
    context_token_budget = 4000

    def flow(self) -> FlowSpec:
        return FlowSpec(
            nodes={
                "load_request": load_request_node,
                "guard": guard_node,
                "shadow_execute": shadow_execute_node,
                "verify": verify_node,
                "gate": hitl_node("gate_approve"),
                "persist": persist_node,
                "save_memory": save_memory_node,
            },
            entry="load_request",
            edges=[
                ("shadow_execute", "verify"),
                ("verify", "gate"),
                ("gate", "save_memory"),
                ("save_memory", "persist"),
            ],
            conditional=[
                ("load_request", route_load, {"ok": "guard", "blocked": "persist"}),
                ("guard", route_guard, {"ok": "shadow_execute", "blocked": "persist"}),
            ],
            end_nodes=["persist"],
        )

    def input_schema(self) -> Optional[dict]:
        return {
            "type": "object",
            "properties": {
                "request_id": {"type": "integer", "description": "approved 变更单ID"},
                "sandbox_connection_id": {"type": "string", "description": "影子库连接ID(env=sandbox)"},
            },
            "required": ["request_id", "sandbox_connection_id"],
        }

    def metadata(self) -> AgentSpec:
        return AgentSpec(
            agent_type="db_release",
            display_name="变更发布",
            description="对已审批变更单在影子库沙箱执行验证，人工确认后输出原样 SQL（不执行生产）",
            intent_labels=("变更发布", "沙箱验证", "db_release"),
            intent_examples=("验证这条变更能否执行", "在影子库跑一下这个 SQL"),
            intent_hint="变更评审通过后，进入沙箱验证/发布",
            scope=Scope.UNIFIED_ASK,
            card=AgentCard(icon="rocket", badge="新", sort_order=3, action_label="开始验证"),
            entry_fields=(
                EntryField(name="request_id", label="变更单ID", type=EntryFieldType.INT, required=True),
                EntryField(
                    name="sandbox_connection_id",
                    label="沙箱数据源ID",
                    type=EntryFieldType.STR,
                    required=True,
                ),
            ),
            templates=("在影子库验证已审批变更",),
            execution_mode="stream",
            # 无 LLM 节点；显式声明结果节点，避免 V6-soft 告警（流式事件仍可用）
            generate_nodes=("verify",),
            tags=("db_release", "database", "sandbox"),
            trace_name="unified.db_release",
        )


if __name__ == "__main__":
    import pathlib
    import sys

    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))
    from backend.app_state import app_state  # noqa: E402

    app_state.checkpointer = None
    output = DbReleaseAgent().export_graph_png("db_release_graph.png")
    print(f"已生成图: {output}")
