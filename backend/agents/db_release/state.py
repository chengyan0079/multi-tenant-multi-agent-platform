"""db_release 状态定义。"""

from __future__ import annotations

from typing import Optional

from typing_extensions import TypedDict


class DbReleaseState(TypedDict, total=False):
    # 审批前段统计（HITL 恢复后与审批后段合并展示）
    gate_token_usage: dict
    gate_latency_ms: int
    messages: list
    tenant_id: int
    user_id: int
    session_id: str
    turn_id: str
    trace_id: str
    query: str

    # 输入（无 SQL）
    request_id: Optional[int]
    sandbox_connection_id: str

    # 执行
    sql_text: str
    db_type: str
    final_sql: str
    release_code: str  # ok / blocked
    exec_result: dict
    exec_ok: bool

    # HITL / 结果
    approval: Optional[dict]
    approval_gate: Optional[str]
    release_status: str
    answer: str
