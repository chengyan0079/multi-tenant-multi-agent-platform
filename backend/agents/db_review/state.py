"""db_review 状态定义。"""

from __future__ import annotations

from typing import Optional

from typing_extensions import TypedDict


class DbReviewState(TypedDict, total=False):
    """数据库变更评审状态。"""

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

    # 输入
    request_id: Optional[int]
    sql_text: str
    db_type: str
    connection_id: str
    target_database: str
    target_tables: list[str]
    script_file_id: Optional[int]
    drill_file_id: Optional[int]

    # 元数据 / 分析
    metadata: dict
    slow_sql: dict
    dimensions: dict
    # 并行预检各分支结果（Send 扇出 + fan-in）
    pre_lock: dict
    pre_rows: dict
    pre_slow: dict
    pre_meta: dict

    # 结论
    risk_level: Optional[str]
    suggestions: list
    approval: Optional[dict]
    approval_gate: Optional[str]
    answer: str
