"""模型配置注册表 DAO。

- 全局表（无 tenant 审计列），审计用 audit_on_insert(with_tenant=False)；
- 运行时取某 model_type 下 enabled 且 sort_order 最小的一条作为 active 模型。
"""
from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import text

from backend.data.sql import execute_write, fetch_all, fetch_one, fetch_value, session_scope
from backend.data.sql.audit import audit_on_insert, audit_on_update

_COLS = (
    "id, model_type, name, provider, base_url, api_key, endpoint_path, "
    "temperature, timeout_s, max_retries, enabled, sort_order, description, updated_at"
)

_LIST = text(f"SELECT {_COLS} FROM agent_model_registry ORDER BY model_type, sort_order, id")
_LIST_BY_TYPE = text(
    f"SELECT {_COLS} FROM agent_model_registry WHERE model_type = :model_type ORDER BY sort_order, id"
)
_GET = text(f"SELECT {_COLS} FROM agent_model_registry WHERE id = :id")
_GET_ACTIVE = text(
    f"SELECT {_COLS} FROM agent_model_registry "
    "WHERE model_type = :model_type AND enabled = true "
    "ORDER BY sort_order, id LIMIT 1"
)
_INSERT = text(
    """
    INSERT INTO agent_model_registry (
        model_type, name, provider, base_url, api_key, endpoint_path,
        temperature, timeout_s, max_retries, enabled, sort_order, description,
        create_user_id, update_user_id
    ) VALUES (
        :model_type, :name, :provider, :base_url, :api_key, :endpoint_path,
        :temperature, :timeout_s, :max_retries, :enabled, :sort_order, :description,
        :create_user_id, :update_user_id
    )
    RETURNING id
    """
)
_UPDATE = text(
    """
    UPDATE agent_model_registry SET
        model_type = :model_type, name = :name, provider = :provider,
        base_url = :base_url, api_key = :api_key, endpoint_path = :endpoint_path,
        temperature = :temperature, timeout_s = :timeout_s, max_retries = :max_retries,
        enabled = :enabled, sort_order = :sort_order, description = :description,
        update_user_id = :update_user_id
    WHERE id = :id
    """
)
_DELETE = text("DELETE FROM agent_model_registry WHERE id = :id")


class ModelDao:
    """模型注册表读写。"""

    @staticmethod
    async def list_models(model_type: Optional[str] = None) -> list[dict[str, Any]]:
        """模型列表（按 model_type 过滤可选，按 sort_order 升序）。"""
        async with session_scope() as session:
            if model_type:
                return await fetch_all(session, _LIST_BY_TYPE, {"model_type": model_type})
            return await fetch_all(session, _LIST)

    @staticmethod
    async def get(model_id: int) -> Optional[dict[str, Any]]:
        """按主键取单条，未命中返回 None。"""
        async with session_scope() as session:
            return await fetch_one(session, _GET, {"id": model_id})

    @staticmethod
    async def get_active(model_type: str) -> Optional[dict[str, Any]]:
        """取某类型下 enabled 且 sort_order 最小的一条；无则返回 None。"""
        async with session_scope() as session:
            return await fetch_one(session, _GET_ACTIVE, {"model_type": model_type})

    @staticmethod
    async def count_enabled(model_type: str) -> int:
        """统计某类型下 enabled=true 的记录数（用于启动期就绪自检）。"""
        async with session_scope() as session:
            return int(
                await fetch_value(
                    session,
                    text(
                        "SELECT COUNT(*) FROM agent_model_registry "
                        "WHERE model_type = :model_type AND enabled = true"
                    ),
                    {"model_type": model_type},
                )
            )

    @staticmethod
    async def create(
        *,
        model_type: str,
        name: str,
        provider: Optional[str] = None,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        endpoint_path: Optional[str] = None,
        temperature: Optional[float] = None,
        timeout_s: Optional[float] = None,
        max_retries: Optional[int] = None,
        enabled: bool = True,
        sort_order: int = 0,
        description: Optional[str] = None,
    ) -> int:
        """新增一条模型记录，返回新主键 id（审计列由 audit_on_insert 注入）。"""
        params = {
            "model_type": model_type,
            "name": name,
            "provider": provider,
            "base_url": base_url,
            "api_key": api_key,
            "endpoint_path": endpoint_path,
            "temperature": temperature,
            "timeout_s": timeout_s,
            "max_retries": max_retries,
            "enabled": enabled,
            "sort_order": sort_order,
            "description": description,
            **audit_on_insert(with_tenant=False),
        }
        async with session_scope() as session:
            new_id = await fetch_value(session, _INSERT, params)
            await session.commit()
            return new_id  # type: ignore[return-value]

    @staticmethod
    async def update(
        model_id: int,
        *,
        model_type: str,
        name: str,
        provider: Optional[str] = None,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        endpoint_path: Optional[str] = None,
        temperature: Optional[float] = None,
        timeout_s: Optional[float] = None,
        max_retries: Optional[int] = None,
        enabled: bool = True,
        sort_order: int = 0,
        description: Optional[str] = None,
    ) -> int:
        """更新一条模型记录（仅刷新 update_user_id 审计列）。"""
        params = {
            "id": model_id,
            "model_type": model_type,
            "name": name,
            "provider": provider,
            "base_url": base_url,
            "api_key": api_key,
            "endpoint_path": endpoint_path,
            "temperature": temperature,
            "timeout_s": timeout_s,
            "max_retries": max_retries,
            "enabled": enabled,
            "sort_order": sort_order,
            "description": description,
            **audit_on_update(with_tenant=False),
        }
        async with session_scope() as session:
            return await execute_write(session, _UPDATE, params)

    @staticmethod
    async def delete(model_id: int) -> int:
        """物理删除一条模型记录，返回影响行数。"""
        async with session_scope() as session:
            return await execute_write(session, _DELETE, {"id": model_id})
