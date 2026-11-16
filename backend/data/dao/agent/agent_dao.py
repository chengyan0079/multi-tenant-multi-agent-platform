"""Agent 目录 DAO（租户级）：agent 表，enabled 由租户控制。"""

from __future__ import annotations

import json
from typing import Any, Optional

from sqlalchemy import Boolean, Integer, bindparam, text

from backend.data.sql import (
    execute_write,
    fetch_all,
    fetch_one,
    fetch_page,
    fetch_value,
    session_scope,
)
from backend.data.sql.audit import audit_on_insert, audit_on_update

_LIST_AGENTS = text("""
SELECT id, tenant_id, agent_type, name, description, input_schema, enabled, version, updated_at
FROM agent
ORDER BY tenant_id, agent_type
""")

_LIST_AGENTS_PAGED = text("""
SELECT id, tenant_id, agent_type, name, description, input_schema, enabled, version, updated_at
FROM agent
WHERE (:tenant_id IS NULL OR tenant_id = :tenant_id)
  AND (:only_enabled = false OR enabled = true)
ORDER BY agent_type
LIMIT :limit OFFSET :offset
""").bindparams(
    bindparam("tenant_id", type_=Integer),
    bindparam("only_enabled", type_=Boolean),
    bindparam("limit", type_=Integer),
    bindparam("offset", type_=Integer),
)
_COUNT_AGENTS_PAGED = text("""
SELECT count(*) FROM agent
WHERE (:tenant_id IS NULL OR tenant_id = :tenant_id)
  AND (:only_enabled = false OR enabled = true)
""").bindparams(
    bindparam("tenant_id", type_=Integer),
    bindparam("only_enabled", type_=Boolean),
)

_GET_AGENT = text("""
SELECT id, tenant_id, agent_type, name, description, input_schema, enabled, version, updated_at
FROM agent
WHERE tenant_id = :tenant_id AND agent_type = :agent_type
""")

_INSERT_AGENT = text("""
INSERT INTO agent (
    tenant_id, agent_type, name, description, input_schema, enabled, version,
    create_user_id, update_user_id
) VALUES (
    :tenant_id, :agent_type, :name, :description, :input_schema, :enabled, :version,
    :create_user_id, :update_user_id
)
RETURNING id
""")

_UPDATE_AGENT = text("""
UPDATE agent SET
    name = :name, description = :description, input_schema = :input_schema,
    enabled = :enabled, version = :version, update_user_id = :update_user_id
WHERE tenant_id = :tenant_id AND agent_type = :agent_type
""")

_SET_ENABLED = text(
    "UPDATE agent SET enabled = :enabled, update_user_id = :update_user_id "
    "WHERE tenant_id = :tenant_id AND agent_type = :agent_type"
)

_DELETE_AGENT = text(
    "DELETE FROM agent WHERE tenant_id = :tenant_id AND agent_type = :agent_type"
)

_GET_ID = text(
    "SELECT id FROM agent WHERE tenant_id = :tenant_id AND agent_type = :agent_type"
)

_LIST_AGENT_TENANTS = text(
    "SELECT tenant_id FROM agent WHERE agent_type = :agent_type ORDER BY tenant_id"
)


def _decode_input_schema(row: dict[str, Any]) -> dict[str, Any]:
    """JSON 列归一化为 dict。"""
    schema = row.get("input_schema")
    if isinstance(schema, str):
        try:
            row["input_schema"] = json.loads(schema)
        except json.JSONDecodeError:
            row["input_schema"] = None
    return row


class AgentDao:
    """租户级 Agent 目录读写（tenant_id + agent_type 唯一，enabled 租户可控）。"""

    @staticmethod
    async def list_agents() -> list[dict[str, Any]]:
        """全部租户的 Agent 元数据（启动期加载用）。"""
        async with session_scope() as session:
            rows = await fetch_all(session, _LIST_AGENTS)
        return [_decode_input_schema(r) for r in rows]

    @staticmethod
    async def list_agents_paged(
        *,
        tenant_id: int | None = None,
        only_enabled: bool = False,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        async with session_scope() as session:
            rows, total = await fetch_page(
                session,
                _LIST_AGENTS_PAGED,
                _COUNT_AGENTS_PAGED,
                {"tenant_id": tenant_id, "only_enabled": only_enabled},
                page=page,
                page_size=page_size,
            )
        return [_decode_input_schema(r) for r in rows], total

    @staticmethod
    async def get_by_type(tenant_id: int, agent_type: str) -> dict[str, Any] | None:
        async with session_scope() as session:
            row = await fetch_one(
                session, _GET_AGENT, {"tenant_id": tenant_id, "agent_type": agent_type}
            )
        return _decode_input_schema(row) if row is not None else None

    @staticmethod
    async def get_id(tenant_id: int, agent_type: str) -> int | None:
        async with session_scope() as session:
            row = await fetch_one(
                session, _GET_ID, {"tenant_id": tenant_id, "agent_type": agent_type}
            )
        return row["id"] if row is not None else None

    @staticmethod
    async def create(
        *,
        tenant_id: int,
        agent_type: str,
        name: str,
        description: str,
        version: str,
        enabled: bool = True,
        input_schema: Optional[str] = None,
    ) -> int:
        async with session_scope() as session:
            new_id = await fetch_value(
                session,
                _INSERT_AGENT,
                {
                    "tenant_id": tenant_id,
                    "agent_type": agent_type,
                    "name": name,
                    "description": description,
                    "input_schema": input_schema,
                    "enabled": enabled,
                    "version": version,
                    **audit_on_insert(with_tenant=False),
                },
            )
            return new_id  # type: ignore[return-value]

    @staticmethod
    async def update(
        tenant_id: int,
        agent_type: str,
        *,
        name: str,
        description: str,
        version: str,
        enabled: bool = True,
        input_schema: Optional[str] = None,
    ) -> int:
        async with session_scope() as session:
            return await execute_write(
                session,
                _UPDATE_AGENT,
                {
                    "tenant_id": tenant_id,
                    "agent_type": agent_type,
                    "name": name,
                    "description": description,
                    "input_schema": input_schema,
                    "enabled": enabled,
                    "version": version,
                    **audit_on_update(with_tenant=False),
                },
            )

    @staticmethod
    async def set_enabled(tenant_id: int, agent_type: str, enabled: bool) -> int:
        async with session_scope() as session:
            return await execute_write(
                session,
                _SET_ENABLED,
                {
                    "tenant_id": tenant_id,
                    "agent_type": agent_type,
                    "enabled": enabled,
                    **audit_on_update(with_tenant=False),
                },
            )

    @staticmethod
    async def delete(tenant_id: int, agent_type: str) -> int:
        async with session_scope() as session:
            return await execute_write(
                session, _DELETE_AGENT, {"tenant_id": tenant_id, "agent_type": agent_type}
            )

    @staticmethod
    async def list_tenants(agent_type: str) -> list[int]:
        """该 agent_type 已绑定的租户列表。"""
        async with session_scope() as session:
            rows = await fetch_all(session, _LIST_AGENT_TENANTS, {"agent_type": agent_type})
        return [int(r["tenant_id"]) for r in rows]
