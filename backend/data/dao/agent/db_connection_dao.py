"""数据库数据源 DAO（租户级）：CRUD + 按 connection_id 取配置。"""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import Integer, String, bindparam, text

from backend.data.sql import (
    execute_write,
    fetch_all,
    fetch_one,
    fetch_page,
    fetch_value,
    session_scope,
)
from backend.data.sql.audit import audit_on_insert, audit_on_update

_COUNT = text(
    "SELECT count(*) FROM agent_db_connection "
    "WHERE tenant_id = :tenant_id AND (:name IS NULL OR name ILIKE '%' || :name || '%')"
).bindparams(bindparam("tenant_id", type_=Integer), bindparam("name", type_=String))

_LIST = text(
    "SELECT * FROM agent_db_connection "
    "WHERE tenant_id = :tenant_id AND (:name IS NULL OR name ILIKE '%' || :name || '%') "
    "ORDER BY name LIMIT :limit OFFSET :offset"
).bindparams(
    bindparam("tenant_id", type_=Integer),
    bindparam("name", type_=String),
    bindparam("limit", type_=Integer),
    bindparam("offset", type_=Integer),
)

_GET = text("SELECT * FROM agent_db_connection WHERE tenant_id = :tenant_id AND id = :id")
_LIST_ONE = text("SELECT * FROM agent_db_connection WHERE tenant_id = :tenant_id ORDER BY name")

_INSERT = text("""
INSERT INTO agent_db_connection (
    tenant_id, name, db_type, host, port, username, password, database, schema_name,
    readonly, enabled, remark, create_user_id, update_user_id
) VALUES (
    :tenant_id, :name, :db_type, :host, :port, :username, :password, :database, :schema_name,
    :readonly, :enabled, :remark, :cu, :uu
) RETURNING id
""")

_UPDATE = text("""
UPDATE agent_db_connection SET
    name = :name, db_type = :db_type, host = :host, port = :port,
    username = :username, password = :password, database = :database,
    schema_name = :schema_name, readonly = :readonly, enabled = :enabled,
    remark = :remark, update_user_id = :uu
WHERE tenant_id = :tenant_id AND id = :id
""")

_SET_ENABLED = text(
    "UPDATE agent_db_connection SET enabled = :enabled, update_user_id = :uu "
    "WHERE tenant_id = :tenant_id AND id = :id"
)
_DELETE = text("DELETE FROM agent_db_connection WHERE tenant_id = :tenant_id AND id = :id")


class DbConnectionDao:
    @staticmethod
    async def list_paged(
        *, tenant_id: int, name: Optional[str] = None, page: int = 1, page_size: int = 20
    ) -> tuple[list[dict[str, Any]], int]:
        async with session_scope() as session:
            rows, total = await fetch_page(
                session,
                _LIST,
                _COUNT,
                {"tenant_id": tenant_id, "name": name},
                page=page,
                page_size=page_size,
            )
        return rows, total

    @staticmethod
    async def get(tenant_id: int, connection_id: str) -> dict[str, Any] | None:
        async with session_scope() as session:
            return await fetch_one(
                session, _GET, {"tenant_id": tenant_id, "id": connection_id}
            )

    @staticmethod
    async def list_by_tenant(tenant_id: int) -> list[dict[str, Any]]:
        async with session_scope() as session:
            return await fetch_all(session, _LIST_ONE, {"tenant_id": tenant_id})

    @staticmethod
    async def create(*, tenant_id: int, **fields: Any) -> str:
        async with session_scope() as session:
            audit = audit_on_insert(with_tenant=False)
            new_id = await fetch_value(
                session,
                _INSERT,
                {"tenant_id": tenant_id, **fields, "cu": audit["create_user_id"], "uu": audit["update_user_id"]},
            )
            return new_id  # type: ignore[return-value]

    @staticmethod
    async def update(tenant_id: int, connection_id: str, **fields: Any) -> int:
        async with session_scope() as session:
            audit = audit_on_update(with_tenant=False)
            return await execute_write(
                session,
                _UPDATE,
                {"tenant_id": tenant_id, "id": connection_id, **fields, "uu": audit["update_user_id"]},
            )

    @staticmethod
    async def set_enabled(tenant_id: int, connection_id: str, enabled: bool) -> int:
        async with session_scope() as session:
            audit = audit_on_update(with_tenant=False)
            return await execute_write(
                session,
                _SET_ENABLED,
                {
                    "tenant_id": tenant_id,
                    "id": connection_id,
                    "enabled": enabled,
                    "uu": audit["update_user_id"],
                },
            )

    @staticmethod
    async def delete(tenant_id: int, connection_id: str) -> int:
        async with session_scope() as session:
            return await execute_write(
                session, _DELETE, {"tenant_id": tenant_id, "id": connection_id}
            )
