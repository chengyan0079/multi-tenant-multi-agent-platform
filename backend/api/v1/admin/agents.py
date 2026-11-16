"""Agent 管理端点（租户级）：元数据目录 + 绑定租户 + 模型绑定。"""

from __future__ import annotations

import json
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query

from backend.api.v1.admin.schemas import (
    AgentIn,
    AgentModelBindIn,
    AgentModelUpdateIn,
    EnabledIn,
)
from backend.app_state import app_state
from backend.broker.publish import publish_config_refresh
from backend.common.response import success
from backend.data.dao.agent.agent_dao import AgentDao
from backend.data.dao.agent.agent_model_rel_dao import AgentModelRelDao
from backend.data.dao.agent.model_dao import ModelDao
from backend.middleware.auth import get_current_user
from backend.observability.exception import BizException, ErrCode
from backend.security.rbac import Scope
from backend.security.security import require_scope

router = APIRouter(prefix="/agents", tags=["admin"])


def _registered_types() -> set[str]:
    reg = app_state.agent_registry
    return set(reg.list_types(only_enabled=False)) if reg else set()


def _item(row: dict[str, Any], registered: bool) -> dict[str, Any]:
    reg = app_state.agent_registry
    schema = row["input_schema"]
    if not schema and reg:
        try:
            schema = reg.get(row["agent_type"]).input_schema
        except KeyError:
            schema = None
    return {
        "tenant_id": row["tenant_id"],
        "agent_type": row["agent_type"],
        "name": row["name"],
        "description": row["description"],
        "version": row["version"],
        "enabled": row.get("enabled"),
        "registered": registered,
        "input_schema": schema,
        "updated_at": row["updated_at"],
    }


def _validate_input_schema(raw: Optional[str]) -> None:
    if raw is None:
        return
    try:
        json.loads(raw)
    except (ValueError, TypeError):
        raise BizException(ErrCode.PARAM_ERROR, "input_schema 不是合法 JSON")  # noqa: B904


def _invalidate_llm_cache() -> None:
    factory = app_state.llm_factory
    if factory is not None:
        factory.clear_llm_cache()


async def _refresh_registry() -> None:
    reg = app_state.agent_registry
    if reg is not None:
        await reg.refresh()
    await publish_config_refresh("agent_registry")


@router.get("", summary="Agent 列表（分页）")
async def list_agents(
    tenant_id: Optional[int] = Query(None, description="按租户过滤；不传则全部"),
    only_enabled: bool = Query(False, description="仅返回该租户下 enabled 的记录"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    _: object = Depends(require_scope(Scope.AGENT_PAGE)),  # noqa: B008
    __: object = Depends(get_current_user),  # noqa: B008
) -> Any:
    registered = _registered_types()
    rows, total = await AgentDao.list_agents_paged(
        tenant_id=tenant_id, only_enabled=only_enabled, page=page, page_size=page_size
    )
    items = [_item(r, r["agent_type"] in registered) for r in rows]
    return success({"items": items, "total": total, "page": page, "page_size": page_size})


@router.get("/{agent_type}", summary="Agent 详情")
async def get_agent(
    agent_type: str,
    tenant_id: int = Query(..., description="租户ID"),
    _: object = Depends(require_scope(Scope.AGENT_VIEW)),  # noqa: B008
    __: object = Depends(get_current_user),  # noqa: B008
):
    row = await AgentDao.get_by_type(tenant_id, agent_type)
    if row is None:
        raise BizException(ErrCode.NOT_FOUND, f"Agent 未登记: {agent_type}")
    return success(_item(row, agent_type in _registered_types()))


# ---------- 绑定租户 ----------


@router.get("/{agent_type}/tenants", summary="已绑定租户")
async def list_agent_tenants(
    agent_type: str,
    _: object = Depends(require_scope(Scope.AGENT_VIEW)),  # noqa: B008
    __: object = Depends(get_current_user),  # noqa: B008
):
    return success(await AgentDao.list_tenants(agent_type))


@router.post("/{agent_type}/tenants", summary="绑定到租户")
async def bind_tenant(
    agent_type: str,
    tenant_id: int = Query(..., description="目标租户ID"),
    _: object = Depends(require_scope(Scope.AGENT_UPDATE)),  # noqa: B008
    __: object = Depends(get_current_user),  # noqa: B008
):
    """为租户绑定 Agent（插入该租户的 agent 行）。"""
    reg = app_state.agent_registry
    if reg is None or not reg.is_registered(agent_type):
        raise BizException(ErrCode.NOT_FOUND, f"Agent 未注册: {agent_type}")
    if await AgentDao.get_by_type(tenant_id, agent_type) is not None:
        raise BizException(ErrCode.PARAM_ERROR, "该租户已绑定此 Agent")
    meta = reg.get(agent_type)
    await AgentDao.create(
        tenant_id=tenant_id,
        agent_type=agent_type,
        name=meta.name or agent_type,
        description=meta.description or "",
        version=meta.version or "1.0.0",
        input_schema=json.dumps(meta.input_schema) if meta.input_schema else None,
    )
    await _refresh_registry()
    return success({"agent_type": agent_type, "tenant_id": tenant_id})


@router.delete("/{agent_type}/tenants/{tenant_id}", summary="解绑租户")
async def unbind_tenant(
    agent_type: str,
    tenant_id: int,
    _: object = Depends(require_scope(Scope.AGENT_DELETE)),  # noqa: B008
    __: object = Depends(get_current_user),  # noqa: B008
):
    if await AgentDao.get_by_type(tenant_id, agent_type) is None:
        raise BizException(ErrCode.NOT_FOUND, "该租户未绑定此 Agent")
    await AgentDao.delete(tenant_id, agent_type)
    await _refresh_registry()
    return success({"agent_type": agent_type, "tenant_id": tenant_id})


# ---------- 租户内启停 ----------


@router.patch("/{agent_type}/enabled", summary="租户内启停")
async def set_agent_enabled(
    agent_type: str,
    body: EnabledIn,
    tenant_id: int = Query(..., description="租户ID"),
    _: object = Depends(require_scope(Scope.AGENT_STATUS)),  # noqa: B008
    __: object = Depends(get_current_user),  # noqa: B008
):
    if await AgentDao.get_by_type(tenant_id, agent_type) is None:
        raise BizException(ErrCode.NOT_FOUND, f"Agent 未登记: {agent_type}")
    await AgentDao.set_enabled(tenant_id, agent_type, body.enabled)
    await _refresh_registry()
    return success(
        {"agent_type": agent_type, "tenant_id": tenant_id, "enabled": body.enabled}
    )


# ---------- 元数据增删改 ----------


@router.post("", summary="新增智能体")
async def create_agent(
    body: AgentIn,
    _: object = Depends(require_scope(Scope.AGENT_ADD)),  # noqa: B008
    __: object = Depends(get_current_user),  # noqa: B008
):
    if await AgentDao.get_by_type(body.tenant_id, body.agent_type) is not None:
        raise BizException(
            ErrCode.PARAM_ERROR, f"该租户下 agent_type 已存在: {body.agent_type}"
        )
    _validate_input_schema(body.input_schema)
    new_id = await AgentDao.create(
        tenant_id=body.tenant_id,
        agent_type=body.agent_type,
        name=body.name,
        description=body.description or "",
        version=body.version,
        input_schema=body.input_schema,
    )
    await _refresh_registry()
    return success({"id": new_id, "agent_type": body.agent_type})


@router.put("/{agent_type}", summary="更新智能体")
async def update_agent(
    agent_type: str,
    body: AgentIn,
    _: object = Depends(require_scope(Scope.AGENT_UPDATE)),  # noqa: B008
    __: object = Depends(get_current_user),  # noqa: B008
):
    if await AgentDao.get_by_type(body.tenant_id, agent_type) is None:
        raise BizException(ErrCode.NOT_FOUND, f"Agent 未登记: {agent_type}")
    _validate_input_schema(body.input_schema)
    await AgentDao.update(
        body.tenant_id,
        agent_type,
        name=body.name,
        description=body.description or "",
        version=body.version,
        input_schema=body.input_schema,
    )
    await _refresh_registry()
    return success({"agent_type": agent_type, "tenant_id": body.tenant_id})


@router.delete("/{agent_type}", summary="删除智能体")
async def delete_agent(
    agent_type: str,
    tenant_id: int = Query(..., description="租户ID"),
    _: object = Depends(require_scope(Scope.AGENT_DELETE)),  # noqa: B008
    __: object = Depends(get_current_user),  # noqa: B008
):
    row = await AgentDao.get_by_type(tenant_id, agent_type)
    if row is None:
        raise BizException(ErrCode.NOT_FOUND, f"Agent 未登记: {agent_type}")
    if await AgentModelRelDao.count_by_agent(row["id"]) > 0:
        raise BizException(ErrCode.PARAM_ERROR, "该智能体已绑定模型，请先到「配置」解绑后再删除")
    await AgentDao.delete(tenant_id, agent_type)
    await _refresh_registry()
    return success({"agent_type": agent_type, "tenant_id": tenant_id})


# ---------- 智能体 ↔ 模型绑定（按租户 agent 行） ----------


@router.get("/{agent_type}/models", summary="智能体模型绑定列表（分页）")
async def list_agent_models(
    agent_type: str,
    tenant_id: int = Query(..., description="租户ID"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    _: object = Depends(require_scope(Scope.AGENT_VIEW)),  # noqa: B008
    __: object = Depends(get_current_user),  # noqa: B008
) -> Any:
    if await AgentDao.get_by_type(tenant_id, agent_type) is None:
        raise BizException(ErrCode.NOT_FOUND, f"Agent 未登记: {agent_type}")
    items, total = await AgentModelRelDao.list_by_agent_paged(agent_type, page, page_size)
    return success({"items": items, "total": total, "page": page, "page_size": page_size})


@router.post("/{agent_type}/models", summary="添加模型绑定")
async def add_agent_model(
    agent_type: str,
    body: AgentModelBindIn,
    tenant_id: int = Query(..., description="租户ID"),
    _: object = Depends(require_scope(Scope.AGENT_UPDATE)),  # noqa: B008
    __: object = Depends(get_current_user),  # noqa: B008
):
    row = await AgentDao.get_by_type(tenant_id, agent_type)
    if row is None:
        raise BizException(ErrCode.NOT_FOUND, f"Agent 未登记: {agent_type}")
    model = await ModelDao.get(body.model_id)
    if model is None:
        raise BizException(ErrCode.NOT_FOUND, f"模型不存在: {body.model_id}")
    agent_id = row["id"]
    if body.is_default:
        await AgentModelRelDao.reset_default(agent_id, model["model_type"], body.model_id)
    await AgentModelRelDao.add(
        agent_id, body.model_id, is_default=body.is_default, priority=body.priority
    )
    _invalidate_llm_cache()
    return success({"agent_type": agent_type, "model_id": body.model_id})


@router.put("/{agent_type}/models/{model_id}", summary="更新绑定（默认/优先级）")
async def update_agent_model(
    agent_type: str,
    model_id: int,
    body: AgentModelUpdateIn,
    tenant_id: int = Query(..., description="租户ID"),
    _: object = Depends(require_scope(Scope.AGENT_UPDATE)),  # noqa: B008
    __: object = Depends(get_current_user),  # noqa: B008
):
    row = await AgentDao.get_by_type(tenant_id, agent_type)
    if row is None:
        raise BizException(ErrCode.NOT_FOUND, f"Agent 未登记: {agent_type}")
    agent_id = row["id"]
    if body.is_default is True:
        model = await ModelDao.get(model_id)
        if model is None:
            raise BizException(ErrCode.NOT_FOUND, f"模型不存在: {model_id}")
        await AgentModelRelDao.reset_default(agent_id, model["model_type"], model_id)
    affected = await AgentModelRelDao.set_default_priority(
        agent_id, model_id, is_default=body.is_default, priority=body.priority
    )
    if affected == 0:
        raise BizException(ErrCode.NOT_FOUND, "绑定不存在")
    _invalidate_llm_cache()
    return success({"agent_type": agent_type, "model_id": model_id})


@router.delete("/{agent_type}/models/{model_id}", summary="解绑模型")
async def remove_agent_model(
    agent_type: str,
    model_id: int,
    tenant_id: int = Query(..., description="租户ID"),
    _: object = Depends(require_scope(Scope.AGENT_DELETE)),  # noqa: B008
    __: object = Depends(get_current_user),  # noqa: B008
):
    row = await AgentDao.get_by_type(tenant_id, agent_type)
    if row is None:
        raise BizException(ErrCode.NOT_FOUND, f"Agent 未登记: {agent_type}")
    await AgentModelRelDao.remove(row["id"], model_id)
    _invalidate_llm_cache()
    return success({"agent_type": agent_type, "model_id": model_id})
