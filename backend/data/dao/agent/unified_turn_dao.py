"""统一会话 turn DAO：agent_unified_turn 读写（§5.2 / §5.3）。

一轮一行，全量正文 + 路由/进度/结果事件 + trace_id；业务历史唯一 source of truth。
所有查询强制 tenant_id + user_id + thread_id（§5.3）。
"""
from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel
from sqlalchemy import text

from backend.orchestration.unified_schemas import ArtifactRef
from backend.data.sql import fetch_all, fetch_value, session_scope


class UnifiedTurnRow(BaseModel):
    """agent_unified_turn 一行（Python 侧具体对象，D17）。"""

    id: str = ""
    tenant_id: int
    user_id: int
    thread_id: str
    trace_id: str | None = None
    turn_index: int
    agent_type: str
    spec_version: str | None = None
    event_type: str
    user_content: str | None = None
    assistant_content: str | None = None
    payload: dict[str, Any] = {}
    routing: dict[str, Any] | None = None
    status: str = "success"
    error_code: str | None = None
    error_msg: str | None = None
    latency_ms: int | None = None
    token_usage: dict[str, Any] | None = None
    session_summary: str | None = None
    create_at: Any | None = None
    # AuditMixin 审计列（表为 NOT NULL，无默认值，写入时由归属用户/租户派生）
    create_user_id: int | None = None
    update_user_id: int | None = None
    create_tenant_id: int | None = None
    update_tenant_id: int | None = None

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "UnifiedTurnRow":
        """DB 行 → 模型：UUID 转 str，JSONB 字符串转 dict（asyncpg 直出类型需归一）。"""
        from uuid import UUID

        data: dict[str, Any] = {}
        for key in cls.model_fields:
            if key not in row:
                continue
            value = row[key]
            if isinstance(value, UUID):
                value = str(value)
            elif key in ("payload", "routing", "token_usage") and isinstance(value, str):
                try:
                    value = json.loads(value)
                except (json.JSONDecodeError, TypeError):
                    value = None
            data[key] = value
        return cls(**data)


_INSERT = text(
    """
INSERT INTO agent_unified_turn
  (id, tenant_id, user_id, thread_id, trace_id, turn_index, agent_type, spec_version,
   event_type, user_content, assistant_content, payload, routing, status,
   error_code, error_msg, latency_ms, token_usage, session_summary,
   create_user_id, update_user_id, create_tenant_id, update_tenant_id)
VALUES
  (:id, :tenant_id, :user_id, :thread_id, :trace_id, :turn_index, :agent_type, :spec_version,
   :event_type, :user_content, :assistant_content,
   CAST(:payload AS JSONB), CAST(:routing AS JSONB), :status,
   :error_code, :error_msg, :latency_ms, CAST(:token_usage AS JSONB), :session_summary,
   :create_user_id, :update_user_id, :create_tenant_id, :update_tenant_id)
RETURNING id
"""
)

_SELECT_COLUMNS = (
    "SELECT id, tenant_id, user_id, thread_id, trace_id, turn_index, agent_type, "
    "spec_version, event_type, user_content, assistant_content, payload, routing, "
    "status, error_code, error_msg, latency_ms, token_usage, session_summary, create_at, "
    "create_user_id, update_user_id, create_tenant_id, update_tenant_id "
    "FROM agent_unified_turn "
)



class UnifiedTurnDao:
    """agent_unified_turn 读写。落库失败直接抛出（不降级），由接口层返回 code/msg。"""

    @staticmethod
    async def get_by_id(turn_id: str, *, tenant_id: int, user_id: int) -> dict[str, Any] | None:
        """按 turn_id 取一行（HITL resume 时读取 pipeline plan/进度）。"""
        async with session_scope() as session:
            rows = await fetch_all(
                session,
                _SELECT_COLUMNS + "WHERE id = :id AND tenant_id = :t AND user_id = :u",
                {"id": turn_id, "t": tenant_id, "u": user_id},
            )
        return rows[0] if rows else None

    @staticmethod
    def _build_insert_params(*, row: UnifiedTurnRow) -> dict[str, Any]:
        """拼装 INSERT 参数：JSON 列序列化 + 审计列由归属用户/租户派生。

        与现有 raw DAO（qa_result_dao / file_dao / agent_dao 等）保持一致：审计列
        显式写入，不依赖 ORM 事件。
        """
        params = row.model_dump()
        params["payload"] = json.dumps(params.get("payload") or {})
        params["routing"] = json.dumps(params.get("routing") or {})
        params["token_usage"] = json.dumps(params.get("token_usage") or {})
        params["create_user_id"] = row.user_id
        params["update_user_id"] = row.user_id
        params["create_tenant_id"] = row.tenant_id
        params["update_tenant_id"] = row.tenant_id
        return params

    @staticmethod
    async def append(*, row: UnifiedTurnRow) -> str:
        """写入一行 turn 并返回新行 id（UUID 字符串）。"""
        params = UnifiedTurnDao._build_insert_params(row=row)
        async with session_scope() as session:
            new_id = await fetch_value(session, _INSERT, params)
            await session.commit()
            return str(new_id)

    @staticmethod
    async def list_recent_by_thread(
        *,
        thread_id: str,
        tenant_id: int,
        user_id: int | None = None,
        limit: int = 200,
    ) -> list[UnifiedTurnRow]:
        """按 (tenant, [user], thread) 读取最近 limit 条 turn（升序）。

        user_id 为空时（管理端）仅按 tenant+thread 过滤。
        """
        where_user = "AND user_id = :user_id" if user_id is not None else ""
        params: dict = {"thread_id": thread_id, "tenant_id": tenant_id, "limit": limit}
        if user_id is not None:
            params["user_id"] = user_id
        sql = text(
            _SELECT_COLUMNS
            + "WHERE thread_id = CAST(:thread_id AS uuid) "
            f"AND tenant_id = :tenant_id {where_user} "
            "ORDER BY turn_index ASC LIMIT :limit"
        )
        async with session_scope() as session:
            rows = await fetch_all(session, sql, params)
            return [UnifiedTurnRow.from_row(r) for r in rows]

    @staticmethod
    async def get_latest_summary(
        *, thread_id: str, tenant_id: int, user_id: int
    ) -> str | None:
        """取该会话最近一条非空摘要（统一层注入子图 existing_summary 用）。"""
        async with session_scope() as session:
            val = await fetch_value(
                session,
                text(
                    "SELECT session_summary FROM agent_unified_turn "
                    "WHERE thread_id = CAST(:tid AS uuid) AND tenant_id = :ten AND user_id = :uid "
                    "AND session_summary IS NOT NULL AND session_summary <> '' "
                    "ORDER BY turn_index DESC LIMIT 1"
                ),
                {"tid": thread_id, "ten": tenant_id, "uid": user_id},
            )
        return str(val) if val else None

    @staticmethod
    async def next_turn_index(*, thread_id: str, tenant_id: int, user_id: int) -> int:
        """取该会话下一轮序号（max+1），供异步回流补写 turn（broker handler 用）。"""
        async with session_scope() as session:
            val = await fetch_value(
                session,
                text(
                    "SELECT coalesce(max(turn_index), 0) + 1 FROM agent_unified_turn "
                    "WHERE thread_id = CAST(:tid AS uuid) AND tenant_id = :ten AND user_id = :uid"
                ),
                {"tid": thread_id, "ten": tenant_id, "uid": user_id},
            )
        return int(val or 1)

    @staticmethod
    async def list_artifacts(
        *, thread_id: str, tenant_id: int, user_id: int
    ) -> list[ArtifactRef]:
        """取会话内所有产物引用（event_type=task_result 且 payload 带 artifact_type）。"""
        async with session_scope() as session:
            rows = await fetch_all(
                session,
                text(
                    "SELECT payload->>'artifact_type' AS artifact_type, "
                    "       payload->>'artifact_id' AS artifact_id, "
                    "       payload->>'route_key' AS route_key "
                    "FROM agent_unified_turn "
                    "WHERE thread_id = CAST(:tid AS uuid) AND tenant_id = :ten AND user_id = :uid "
                    "AND payload->>'artifact_type' IS NOT NULL"
                ),
                {"tid": thread_id, "ten": tenant_id, "uid": user_id},
            )
            return [
                ArtifactRef(
                    artifact_type=r["artifact_type"],
                    artifact_id=r["artifact_id"],
                    route_key=r["route_key"] or "",
                )
                for r in rows
            ]
