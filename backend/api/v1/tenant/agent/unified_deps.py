"""统一咨询入口端点共享依赖：编排图装配 + 响应序列化。

端点层只做「鉴权 + 取 app_state + 装配 UnifiedGraph + 协议转换」，不含业务编排逻辑。
编排、鉴权、回写统一在 UnifiedGraph 内闭环。
"""
from __future__ import annotations

import uuid

from backend.data.dao.agent.thread_dao import ThreadDao
from backend.orchestration.unified_graph import UnifiedGraph
from backend.services.intent_router import classify_as_intent
from backend.services.unified_conversation import UnifiedConversationService


def build_unified_graph(app_state) -> UnifiedGraph:
    """按当前 app_state 装配统一编排图（每次请求轻量构建，依赖均为单例/无状态）。"""
    return UnifiedGraph(
        thread_dao=ThreadDao,
        conversation_service=UnifiedConversationService(),
        orchestrator=app_state.orchestrator,
        registry=app_state.agent_registry,
        # 入口意图识别：规则优先（快/确定），替代默认 LLM 分类；多 Agent 流程走 /entry-orchestrate
        classify_fn=classify_as_intent,
    )


def to_session_item(row: dict) -> "object":
    """DB 行 → 会话列表项 DTO。延迟导入避免循环。"""
    from backend.api.v1.tenant.agent.unified_dtos import SessionListItem

    return SessionListItem(
        thread_id=str(row["id"]),
        session_id=row["session_key"],
        title=row.get("title") or "",
        status=row.get("status") or "",
        agent_type=row.get("last_agent_type") or "",
        turn_count=int(row.get("turn_count") or 0),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


def _get(r: object, key: str, default=None):
    """兼容 dict 与 pydantic 对象的字段读取（turn 行两种形态都可能出现）。"""
    if isinstance(r, dict):
        return r.get(key, default)
    return getattr(r, key, default)


def to_turn_replay(rows: list) -> list:
    from backend.api.v1.tenant.agent.unified_dtos import TurnReplayItem

    out: list = []
    for r in rows:
        payload = _get(r, "payload")
        if not isinstance(payload, dict):
            payload = {}
        out.append(
            TurnReplayItem(
                turn_index=int(_get(r, "turn_index", 0) or 0),
                agent_type=_get(r, "agent_type") or "",
                event_type=_get(r, "event_type") or "",
                user_content=_get(r, "user_content"),
                assistant_content=_get(r, "assistant_content"),
                payload=payload,
                status=_get(r, "status") or "success",
                error_code=_get(r, "error_code"),
                latency_ms=_get(r, "latency_ms"),
                token_usage=_get(r, "token_usage"),
                create_at=_get(r, "create_at"),
            )
        )
    return out


def to_session_detail(row: dict, turns: list) -> "object":
    from backend.api.v1.tenant.agent.unified_dtos import SessionDetail

    item = to_session_item(row)
    return SessionDetail(
        thread_id=item.thread_id,
        session_id=item.session_id,
        title=item.title,
        status=item.status,
        agent_type=item.agent_type,
        turn_count=item.turn_count,
        total_tokens=int(row.get("total_tokens") or 0),
        total_latency_ms=int(row.get("total_latency_ms") or 0),
        created_at=item.created_at,
        updated_at=item.updated_at,
        turns=to_turn_replay(turns),
    )


def new_session_key() -> str:
    return uuid.uuid4().hex
