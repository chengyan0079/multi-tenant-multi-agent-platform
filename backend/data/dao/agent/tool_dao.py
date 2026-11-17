"""工具目录 DAO（租户级）：agent_tool 表 CRUD + 运行配置读取 + 绑定租户。"""

from __future__ import annotations

import json
from typing import Any, Optional

from sqlalchemy import Boolean, Integer, String, bindparam, text

from backend.data.sql import (
    execute_write,
    fetch_all,
    fetch_one,
    fetch_page,
    fetch_value,
    session_scope,
)

_GET_CONFIG = text(
    "SELECT config FROM agent_tool WHERE tenant_id = :tenant_id AND name = :name AND enabled = true"
)

_LIST = text("""
SELECT id, tenant_id, name, plugin, description, schema, config, enabled, create_at, updated_at
FROM agent_tool
WHERE (:tenant_id IS NULL OR tenant_id = :tenant_id)
  AND (:name IS NULL OR name ILIKE '%' || :name || '%')
  AND (:enabled IS NULL OR enabled = :enabled)
ORDER BY tenant_id, name
LIMIT :limit OFFSET :offset
""").bindparams(
    bindparam("tenant_id", type_=Integer),
    bindparam("name", type_=String),
    bindparam("enabled", type_=Boolean),
    bindparam("limit", type_=Integer),
    bindparam("offset", type_=Integer),
)

_COUNT = text("""
SELECT count(*) FROM agent_tool
WHERE (:tenant_id IS NULL OR tenant_id = :tenant_id)
  AND (:name IS NULL OR name ILIKE '%' || :name || '%')
  AND (:enabled IS NULL OR enabled = :enabled)
""").bindparams(
    bindparam("tenant_id", type_=Integer),
    bindparam("name", type_=String),
    bindparam("enabled", type_=Boolean),
)

_GET = text("""
SELECT id, tenant_id, name, plugin, description, schema, config, enabled, create_at, updated_at
FROM agent_tool WHERE id = :id
""")

_INSERT = text("""
INSERT INTO agent_tool (tenant_id, name, plugin, description, schema, config, enabled)
VALUES (:tenant_id, :name, :plugin, :description, :schema, :config, :enabled)
RETURNING id
""")

_UPDATE = text("""
UPDATE agent_tool SET
    name = :name, plugin = :plugin, description = :description,
    schema = :schema, config = :config, enabled = :enabled
WHERE id = :id
""")

_SET_ENABLED = text("UPDATE agent_tool SET enabled = :enabled WHERE id = :id")

_DELETE = text("DELETE FROM agent_tool WHERE id = :id")

_BIND_TENANT = text("""
INSERT INTO agent_tool (tenant_id, name, plugin, description, schema, config, enabled)
SELECT :tenant_id, name, plugin, description, schema, config, enabled
FROM agent_tool WHERE id = :id
ON CONFLICT (tenant_id, name) DO NOTHING
""")

_LIST_TENANTS = text(
    "SELECT tenant_id FROM agent_tool WHERE name = :name ORDER BY tenant_id"
)


_IS_ENABLED = text(
    "SELECT 1 FROM agent_tool "
    "WHERE tenant_id = :tenant_id AND name = :name AND enabled = true"
)


async def is_tool_enabled(tenant_id: int, name: str) -> bool:
    """判断某租户是否启用了指定工具（DB 为准，供 MCP 等非注册表工具使用）。"""
    async with session_scope() as session:
        return await fetch_one(session, _IS_ENABLED, {"tenant_id": tenant_id, "name": name}) is not None


async def get_tool_config(name: str, tenant_id: int = 0) -> dict[str, Any]:
    """读工具运行配置（JSON）；仅取该租户下 enabled=true 的工具。"""
    async with session_scope() as s:
        raw = await fetch_value(s, _GET_CONFIG, {"tenant_id": tenant_id, "name": name})
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}


class ToolDao:
    @staticmethod
    async def list_all_enabled() -> list[dict[str, Any]]:
        """所有租户启用的本地工具（tenant_id, name, plugin）；排除走 MCP 协议的工具。"""
        async with session_scope() as session:
            return await fetch_all(
                session,
                text(
                    "SELECT tenant_id, name, plugin FROM agent_tool "
                    "WHERE enabled = true AND (plugin IS NULL OR plugin <> 'mcp') "
                    "ORDER BY tenant_id, name"
                ),
            )

    @staticmethod
    async def list_tenant_enabled(tenant_id: int) -> list[str]:
        """指定租户启用的工具名列表。"""
        async with session_scope() as session:
            rows = await fetch_all(
                session,
                text(
                    "SELECT name FROM agent_tool WHERE tenant_id=:t AND enabled = true "
                    "ORDER BY name"
                ),
                {"t": tenant_id},
            )
        return [r["name"] for r in rows]
    """agent_tool 租户级读写（enabled 由租户控制）。"""

    @staticmethod
    async def list_paged(
        *,
        tenant_id: Optional[int] = None,
        name: Optional[str] = None,
        enabled: Optional[bool] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        async with session_scope() as session:
            rows, total = await fetch_page(
                session,
                _LIST,
                _COUNT,
                {"tenant_id": tenant_id, "name": name, "enabled": enabled},
                page=page,
                page_size=page_size,
            )
        return rows, total

    @staticmethod
    async def get(tool_id: str) -> dict[str, Any] | None:
        async with session_scope() as session:
            return await fetch_one(session, _GET, {"id": tool_id})

    @staticmethod
    async def create(
        *,
        tenant_id: int,
        name: str,
        plugin: str = "",
        description: str = "",
        schema: str = "{}",
        config: str = "{}",
        enabled: bool = True,
    ) -> str:
        async with session_scope() as session:
            new_id = await fetch_value(
                session,
                _INSERT,
                {
                    "tenant_id": tenant_id,
                    "name": name,
                    "plugin": plugin,
                    "description": description,
                    "schema": schema,
                    "config": config,
                    "enabled": enabled,
                },
            )
            return new_id  # type: ignore[return-value]

    @staticmethod
    async def update(
        tool_id: str,
        *,
        name: str,
        plugin: str = "",
        description: str = "",
        schema: str = "{}",
        config: str = "{}",
        enabled: bool = True,
    ) -> int:
        async with session_scope() as session:
            return await execute_write(
                session,
                _UPDATE,
                {
                    "id": tool_id,
                    "name": name,
                    "plugin": plugin,
                    "description": description,
                    "schema": schema,
                    "config": config,
                    "enabled": enabled,
                },
            )

    @staticmethod
    async def set_enabled(tool_id: str, enabled: bool) -> int:
        async with session_scope() as session:
            return await execute_write(
                session, _SET_ENABLED, {"id": tool_id, "enabled": enabled}
            )

    @staticmethod
    async def delete(tool_id: str) -> int:
        async with session_scope() as session:
            return await execute_write(session, _DELETE, {"id": tool_id})

    @staticmethod
    async def bind_tenant(tool_id: str, tenant_id: int) -> None:
        """把某工具配置复制绑定到目标租户（已存在则跳过）。"""
        async with session_scope() as session:
            await session.execute(_BIND_TENANT, {"id": tool_id, "tenant_id": tenant_id})
            await session.commit()

    @staticmethod
    async def list_tenants(name: str) -> list[int]:
        async with session_scope() as session:
            rows = await fetch_all(session, _LIST_TENANTS, {"name": name})
        return [int(r["tenant_id"]) for r in rows]
