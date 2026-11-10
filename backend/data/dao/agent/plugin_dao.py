"""插件注册表 DAO（agent_plugin）。"""

from __future__ import annotations

from typing import Any

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

_BINDS = (
    # todo asyncpg 扩展协议下 "IS NULL" 参数无法推断类型，需显式声明
    bindparam("name", type_=String),
    bindparam("status", type_=String),
)
_LIST = text("""
SELECT id, name, version, capabilities, status, config, registered_at,
       tenant_id, user_id, create_at, updated_at
FROM agent_plugin
WHERE (:name IS NULL OR name ILIKE '%' || :name || '%')
  AND (:status IS NULL OR status = :status)
ORDER BY registered_at DESC, name LIMIT :limit OFFSET :offset
""").bindparams(*_BINDS, bindparam("limit", type_=Integer), bindparam("offset", type_=Integer))
_COUNT = text("""
SELECT count(*) FROM agent_plugin
WHERE (:name IS NULL OR name ILIKE '%' || :name || '%')
  AND (:status IS NULL OR status = :status)
""").bindparams(*_BINDS)
_GET = text("""
SELECT id, name, version, capabilities, status, config, registered_at,
       tenant_id, user_id, create_at, updated_at
FROM agent_plugin WHERE id = :id
""")
_GET_BY_NAME = text("SELECT id FROM agent_plugin WHERE name = :name")
_LIST_ENABLED = text("""
SELECT name, version, capabilities, config FROM agent_plugin
WHERE status = 'enabled'
ORDER BY name
""")
_INSERT = text(
    """
    INSERT INTO agent_plugin (
        name, version, capabilities, status, config,
        tenant_id, user_id, create_user_id, update_user_id
    ) VALUES (
        :name, :version, :capabilities, :status, :config,
        :tenant_id, :user_id, :create_user_id, :update_user_id
    )
    RETURNING id
    """
)
_UPDATE = text(
    """
    UPDATE agent_plugin SET
        version = :version, capabilities = :capabilities, status = :status,
        config = :config, user_id = :user_id,
        update_user_id = :update_user_id, updated_at = now()
    WHERE id = :id
    """
)
_SET_STATUS = text(
    """
    UPDATE agent_plugin SET status = :status,
        update_user_id = :update_user_id, updated_at = now()
    WHERE id = :id
    """
)
_DELETE = text("DELETE FROM agent_plugin WHERE id = :id")


class PluginDao:
    """插件注册表读写（分页列表、CRUD、状态变更）。"""

    @staticmethod
    async def list_paged(
        name: str | None = None,
        status: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        params = {"name": name, "status": status}
        async with session_scope() as session:
            return await fetch_page(session, _LIST, _COUNT, params, page=page, page_size=page_size)

    @staticmethod
    async def get(plugin_id: str) -> dict[str, Any] | None:
        async with session_scope() as session:
            return await fetch_one(session, _GET, {"id": plugin_id})

    @staticmethod
    async def list_enabled() -> list[dict[str, Any]]:
        async with session_scope() as session:
            return await fetch_all(session, _LIST_ENABLED)

    @staticmethod
    async def name_exists(name: str, exclude_id: str | None = None) -> bool:
        async with session_scope() as session:
            if exclude_id is None:
                row = await fetch_one(session, _GET_BY_NAME, {"name": name})
                return row is not None
            row = await fetch_one(
                session,
                text("SELECT id FROM agent_plugin WHERE name = :name AND id <> :id"),
                {"name": name, "id": exclude_id},
            )
            return row is not None

    @staticmethod
    async def create(
        *,
        name: str,
        version: str,
        capabilities: str,
        status: str,
        config: str,
        tenant_id: int,
        user_id: int,
    ) -> str:
        params = {
            "name": name,
            "version": version,
            "capabilities": capabilities,
            "status": status,
            "config": config,
            "tenant_id": tenant_id,
            "user_id": user_id,
            **audit_on_insert(with_tenant=False),
        }
        async with session_scope() as session:
            new_id = await fetch_value(session, _INSERT, params)
            await session.commit()
            return str(new_id)

    @staticmethod
    async def update(
        plugin_id: str,
        *,
        version: str,
        capabilities: str,
        status: str,
        config: str,
        user_id: int,
    ) -> int:
        params = {
            "id": plugin_id,
            "version": version,
            "capabilities": capabilities,
            "status": status,
            "config": config,
            "user_id": user_id,
            **audit_on_update(with_tenant=False),
        }
        async with session_scope() as session:
            return await execute_write(session, _UPDATE, params)

    @staticmethod
    async def set_status(plugin_id: str, status: str) -> int:
        params = {"id": plugin_id, "status": status, **audit_on_update(with_tenant=False)}
        async with session_scope() as session:
            return await execute_write(session, _SET_STATUS, params)

    @staticmethod
    async def delete(plugin_id: str) -> int:
        async with session_scope() as session:
            return await execute_write(session, _DELETE, {"id": plugin_id})
