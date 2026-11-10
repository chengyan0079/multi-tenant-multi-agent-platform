"""Agent 目录与租户开通策略 DAO：agent/agent_capability_policy 两表，只承载可持久化元数据。"""

from __future__ import annotations

import json
from typing import Any, Optional, Sequence

from sqlalchemy import ARRAY, Boolean, Integer, String, bindparam, text

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
SELECT id, agent_type, name, description, input_schema, enabled, version, updated_at
FROM agent
ORDER BY agent_type
""")

_AGENTS_FROM = """
FROM agent a
LEFT JOIN agent_capability_policy p
       ON p.agent_type = a.agent_type AND p.tenant_id = CAST(:tenant_id AS BIGINT)
WHERE (:only_enabled = false
       OR (a.enabled = true AND a.agent_type = ANY(CAST(:registered_types AS text[]))))
"""
_AGENTS_BINDS = (
    # todo asyncpg 无法从 IS NULL / ANY 推断参数类型，需显式声明
    bindparam("tenant_id", type_=Integer),
    bindparam("only_enabled", type_=Boolean),
    bindparam("registered_types", type_=ARRAY(String)),
)
_LIST_AGENTS_PAGED = text(
    "SELECT a.id, a.agent_type, a.name, a.description, a.input_schema, "
    "a.enabled, a.version, a.updated_at, "
    "COALESCE(p.enabled, true) AS tenant_enabled, "
    f"(p.agent_type IS NOT NULL) AS policy_configured {_AGENTS_FROM} "
    "ORDER BY a.agent_type LIMIT :limit OFFSET :offset"
).bindparams(
    *_AGENTS_BINDS,
    bindparam("limit", type_=Integer),
    bindparam("offset", type_=Integer),
)
_COUNT_AGENTS_PAGED = text(f"SELECT count(*) {_AGENTS_FROM}").bindparams(*_AGENTS_BINDS)

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

_INSERT_AGENT = text("""
INSERT INTO agent (
    agent_type, name, description, input_schema, enabled, version,
    create_user_id, update_user_id
) VALUES (
    :agent_type, :name, :description, :input_schema, :enabled, :version,
    :create_user_id, :update_user_id
)
RETURNING id
""")

_UPDATE_AGENT = text("""
UPDATE agent SET
    name = :name, description = :description, input_schema = :input_schema,
    enabled = :enabled, version = :version, update_user_id = :update_user_id
WHERE agent_type = :agent_type
""")

_DELETE_AGENT = text("DELETE FROM agent WHERE agent_type = :agent_type")

_GET_ID = text("SELECT id FROM agent WHERE agent_type = :agent_type")


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
    async def list_agents_paged(
        *,
        tenant_id: int | None = None,
        only_enabled: bool = False,
        registered_types: Sequence[str] = (),
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        params = {
            "tenant_id": tenant_id,
            "only_enabled": only_enabled,
            "registered_types": list(registered_types),
        }
        async with session_scope() as session:
            rows, total = await fetch_page(
                session,
                _LIST_AGENTS_PAGED,
                _COUNT_AGENTS_PAGED,
                params,
                page=page,
                page_size=page_size,
            )
        return [_decode_input_schema(r) for r in rows], total

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

    @staticmethod
    async def get_id(agent_type: str) -> int | None:
        """按业务键取主键 id，未登记返回 None。"""
        async with session_scope() as session:
            row = await fetch_one(session, _GET_ID, {"agent_type": agent_type})
        return row["id"] if row is not None else None

    @staticmethod
    async def create(
        *,
        agent_type: str,
        name: str,
        description: str,
        version: str,
        enabled: bool,
        input_schema: Optional[str] = None,
    ) -> int:
        """新增一条 Agent 目录行（纯目录维护，允许代码未注册的 agent_type）。"""
        async with session_scope() as session:
            new_id = await fetch_value(
                session,
                _INSERT_AGENT,
                {
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
        agent_type: str,
        *,
        name: str,
        description: str,
        version: str,
        enabled: bool,
        input_schema: Optional[str] = None,
    ) -> int:
        """更新 Agent 元数据（input_schema 传入则为新 JSON 文本，None 表示不动）。"""
        async with session_scope() as session:
            return await execute_write(
                session,
                _UPDATE_AGENT,
                {
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
    async def delete(agent_type: str) -> int:
        """物理删除 Agent 目录行（绑定清理由调用方在删前校验）。"""
        async with session_scope() as session:
            return await execute_write(session, _DELETE_AGENT, {"agent_type": agent_type})
