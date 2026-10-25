"""Agent 目录与租户开通策略 DAO：`agent` / `agent_capability_policy` 两表。

- `agent` 是全局目录（无 tenant 审计列），`agent_type` 为业务键；
- `agent_capability_policy` 是租户级开通策略，(tenant_id, agent_type) 唯一，未配置视为开通。

两表都只承载可持久化元数据，图构造器仍在 AgentRegistry 里由代码注册。
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text

from backend.data.sql import execute_write, fetch_all, fetch_one, session_scope
from backend.data.sql.audit import audit_on_insert

_LIST_AGENTS = text("""
SELECT id, agent_type, name, description, input_schema, enabled, version, updated_at
FROM agent
ORDER BY agent_type
""")

_GET_AGENT = text("""
SELECT id, agent_type, name, description, input_schema, enabled, version, updated_at
FROM agent
WHERE agent_type = :agent_type
""")

# 库未登记但代码已注册时补登记；已存在则只改开关
_UPSERT_AGENT = text("""
INSERT INTO agent (
    agent_type, name, description, enabled, version, create_user_id, update_user_id
) VALUES (
    :agent_type, :name, :description, :enabled, :version, :create_user_id, :update_user_id
)
ON CONFLICT (agent_type) DO UPDATE
SET enabled = EXCLUDED.enabled, update_user_id = EXCLUDED.update_user_id
""")

_LIST_POLICIES = text("""
SELECT tenant_id, agent_type, enabled
FROM agent_capability_policy
ORDER BY tenant_id, agent_type
""")

_LIST_TENANT_POLICIES = text("""
SELECT tenant_id, agent_type, enabled
FROM agent_capability_policy
WHERE tenant_id = :tenant_id
ORDER BY agent_type
""")

# 冲突时只刷新开通状态与更新人，不动创建人（首次写入才记创建人）
_UPSERT_POLICY = text("""
INSERT INTO agent_capability_policy (
    tenant_id, agent_type, enabled,
    create_user_id, update_user_id, create_tenant_id, update_tenant_id
) VALUES (
    :tenant_id, :agent_type, :enabled,
    :create_user_id, :update_user_id, :create_tenant_id, :update_tenant_id
)
ON CONFLICT (tenant_id, agent_type) DO UPDATE
SET enabled = EXCLUDED.enabled,
    update_user_id = EXCLUDED.update_user_id,
    update_tenant_id = EXCLUDED.update_tenant_id
""")


def _decode_input_schema(row: dict[str, Any]) -> dict[str, Any]:
    """JSON 列归一化为 dict。

    text() 查询没有列类型信息，驱动会把 json 列原样返回字符串；
    这里统一转一次，调用方拿到的就永远是 dict/None。
    """
    schema = row.get("input_schema")
    if isinstance(schema, str):
        try:
            row["input_schema"] = json.loads(schema)
        except json.JSONDecodeError:
            row["input_schema"] = None
    return row


class AgentDao:
    """Agent 目录与租户开通策略读写。"""

    @staticmethod
    async def list_agents() -> list[dict[str, Any]]:
        """全部 Agent 元数据（按 agent_type 排序）。"""
        async with session_scope() as session:
            rows = await fetch_all(session, _LIST_AGENTS)
        return [_decode_input_schema(r) for r in rows]

    @staticmethod
    async def get_by_type(agent_type: str) -> dict[str, Any] | None:
        """按业务键取单个 Agent，未登记返回 None。"""
        async with session_scope() as session:
            row = await fetch_one(session, _GET_AGENT, {"agent_type": agent_type})
        return _decode_input_schema(row) if row is not None else None

    @staticmethod
    async def upsert(agent_type: str, *, name: str, enabled: bool) -> None:
        """补登记或更新全局开关（catalog 里 PATCH 启停走这里）。"""
        async with session_scope() as session:
            await session.execute(
                _UPSERT_AGENT,
                {
                    "agent_type": agent_type,
                    "name": name,
                    "description": "",
                    "enabled": enabled,
                    "version": "1.0.0",
                    **audit_on_insert(with_tenant=False),
                },
            )
            await session.commit()

    @staticmethod
    async def list_policies(tenant_id: int | None = None) -> list[dict[str, Any]]:
        """开通策略：传 tenant_id 只取该租户，否则全量（启动期加载用）。"""
        async with session_scope() as session:
            if tenant_id is None:
                return await fetch_all(session, _LIST_POLICIES)
            return await fetch_all(session, _LIST_TENANT_POLICIES, {"tenant_id": tenant_id})

    @staticmethod
    async def set_policies(tenant_id: int, items: list[tuple[str, bool]]) -> int:
        """批量写入租户策略（单事务），返回影响行数。

        批量而非逐条提交：一次 PATCH 里若干条策略要么都生效要么都不生效，
        免得中途失败留下半套配置。
        """
        audit = audit_on_insert(tenant_id=tenant_id)
        async with session_scope() as session:
            affected = 0
            for agent_type, enabled in items:
                affected += await execute_write(
                    session,
                    _UPSERT_POLICY,
                    {
                        "tenant_id": tenant_id,
                        "agent_type": agent_type,
                        "enabled": enabled,
                        **audit,
                    },
                )
            await session.commit()
        return affected
