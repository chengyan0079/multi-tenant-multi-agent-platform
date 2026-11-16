"""DbReviewAgent：数据库变更评审 Agent（基于 AgentTemplate）。"""

from __future__ import annotations

from typing import Optional

from backend.agents.db_review.nodes import (
    aggregate_node,
    fanout_prechecks,
    fetch_metadata_node,
    grade_node,
    load_node,
    persist_node,
    save_memory_node,
    pre_lock_node,
    pre_meta_node,
    pre_rows_node,
    pre_slow_node,
    route_load,
    route_risk,
    suggest_node,
)
from backend.agents.db_review.state import DbReviewState
from backend.agents.template import AgentTemplate, FlowSpec, hitl_node
from backend.orchestration.agent_spec import AgentSpec
from backend.orchestration.unified_schemas import AgentCard, EntryField, EntryFieldType
from backend.security.rbac import Scope


class DbReviewAgent(AgentTemplate):
    agent_type = "db_review"
    state_cls = DbReviewState
    context_token_budget = 4000

    def flow(self) -> FlowSpec:
        return FlowSpec(
            nodes={
                "load": load_node,
                "fetch": fetch_metadata_node,
                "pre_lock": pre_lock_node,
                "pre_rows": pre_rows_node,
                "pre_slow": pre_slow_node,
                "pre_meta": pre_meta_node,
                "aggregate": aggregate_node,
                "grade": grade_node,
                "suggest": suggest_node,
                "approve": hitl_node("change_approve"),
                "persist": persist_node,
                "save_memory": save_memory_node,
            },
            entry="load",
            edges=[
                # fetch 后并行扇出 4 路预检（同一源多条出边 = 并行 fan-out）
                ("fetch", "pre_lock"),
                ("fetch", "pre_rows"),
                ("fetch", "pre_slow"),
                ("fetch", "pre_meta"),
                # 各预检 fan-in 到 aggregate（聚合节点等待全部前驱）
                ("pre_lock", "aggregate"),
                ("pre_rows", "aggregate"),
                ("pre_slow", "aggregate"),
                ("pre_meta", "aggregate"),
                ("aggregate", "grade"),
                ("grade", "suggest"),
                ("approve", "save_memory"),
                ("save_memory", "persist"),
            ],
            conditional=[
                ("load", route_load, {"ok": "fetch", "blocked": "persist"}),
                ("suggest", route_risk, {"low": "persist", "approve": "approve"}),
            ],
            end_nodes=["persist"],
        )

    def input_schema(self) -> Optional[dict]:
        return {
            "type": "object",
            "properties": {
                "sql_text": {"type": "string", "description": "SQL 脚本或长字符串"},
                "db_type": {"type": "string", "enum": ["mysql", "postgresql"]},
                "connection_id": {"type": "string", "description": "数据源ID（图内唯一）"},
                "target_database": {"type": "string"},
                "target_tables": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["sql_text", "db_type", "connection_id"],
        }

    def metadata(self) -> AgentSpec:
        return AgentSpec(
            agent_type="db_review",
            display_name="变更评审",
            description="数据库变更评审：元数据预检→慢SQL/风险分级→优化建议→人工审批（只分析不执行）",
            intent_labels=("变更评审", "SQL评审", "数据库变更", "db_review"),
            intent_examples=("帮我评审这条 ALTER TABLE 的风险", "这个 UPDATE 会不会锁表"),
            intent_hint="涉及数据库变更/SQL 风险评审时路由到此",
            scope=Scope.UNIFIED_ASK,
            card=AgentCard(icon="database", badge="新", sort_order=2, action_label="开始评审"),
            entry_fields=(
                EntryField(name="sql_text", label="SQL 脚本", type=EntryFieldType.STR, required=True),
                EntryField(
                    name="db_type",
                    label="数据库类型",
                    type=EntryFieldType.ENUM,
                    required=True,
                    options=["mysql", "postgresql"],
                ),
                EntryField(
                    name="connection_id",
                    label="数据源ID",
                    type=EntryFieldType.STR,
                    required=True,
                ),
                EntryField(
                    name="target_database",
                    label="目标库",
                    type=EntryFieldType.STR,
                    required=True,
                ),
            ),
            templates=("ALTER TABLE orders ADD COLUMN remark varchar(64);",),
            execution_mode="stream",
            generate_nodes=("grade", "suggest"),
            tags=("db_review", "database", "sql"),
            trace_name="unified.db_review",
        )


if __name__ == "__main__":
    import pathlib
    import sys

    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))
    from backend.app_state import app_state  # noqa: E402

    app_state.checkpointer = None
    output = DbReviewAgent().export_graph_png("db_review_graph.png")
    print(f"已生成图: {output}")
