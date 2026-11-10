"""Agent 管理端点（超管）：元数据目录、全局启停、租户级开通策略与模型绑定。"""

from __future__ import annotations

import json
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query

from backend.api.v1.admin.schemas import (
    AgentIn,
    AgentModelBindIn,
    AgentModelUpdateIn,
    CapabilityIn,
    EnabledIn,
)
from backend.app_state import app_state
from backend.broker.publish import publish_config_refresh
from backend.common.response import success
from backend.observability.exception import BizException, ErrCode
from backend.data.dao.agent.agent_dao import AgentDao
from backend.data.dao.agent.agent_model_rel_dao import AgentModelRelDao
from backend.data.dao.agent.model_dao import ModelDao
from backend.middleware.auth import get_current_user
from backend.security.rbac import Scope
from backend.security.security import require_scope

router = APIRouter(prefix="/agents", tags=["admin"])


def _registered_types() -> set[str]:
    """代码注册的 agent_type 集合（用于标记「已注册/仅库登记」）。"""
    reg = app_state.agent_registry
    return set(reg.list_types(only_enabled=False)) if reg else set()


def _item(row: dict[str, Any], registered: bool) -> dict[str, Any]:
    """库行 + 注册状态拼装成对外的 Agent 视图。"""
    reg = app_state.agent_registry
    schema = row["input_schema"]
    if not schema and reg:
        try:
            schema = reg.get(row["agent_type"]).input_schema
        except KeyError:
            schema = None
    return {
        "agent_type": row["agent_type"],
        "name": row["name"],
        "description": row["description"],
        "version": row["version"],
        "enabled": row["enabled"],
        "registered": registered,
        "input_schema": schema,
        "updated_at": row["updated_at"],
    }


@router.get("", summary="Agent 列表（分页）")
async def list_agents(
    tenant_id: Optional[int] = Query(None, description="传则附带该租户的开通状态"),
    only_enabled: bool = Query(False, description="仅返回全局启用且已注册的"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    _: object = Depends(require_scope(Scope.AGENT_PAGE)),  # noqa: B008
    __: object = Depends(get_current_user),  # noqa: B008
) -> Any:
    """分页查询 Agent 目录。

    请求：query { tenant_id?, only_enabled?, page, page_size }
    权限：agent:page
    返回：items(含 registered/tenant_enabled) / total / page / page_size
    """
    registered = _registered_types()
    rows, total = await AgentDao.list_agents_paged(
        tenant_id=tenant_id,
        only_enabled=only_enabled,
        registered_types=sorted(registered),
        page=page,
        page_size=page_size,
    )
    items = []
    for r in rows:
        item = _item(r, r["agent_type"] in registered)
        if tenant_id is not None:
            item["tenant_enabled"] = r["tenant_enabled"]
        items.append(item)
    return success({"items": items, "total": total, "page": page, "page_size": page_size})


@router.get("/{agent_type}", summary="Agent 详情")
async def get_agent(
    agent_type: str,
    _: object = Depends(require_scope(Scope.AGENT_VIEW)),
    __: object = Depends(get_current_user),
):  # noqa: B008
    """获取单个 Agent 详情（库行 + 注册状态）。

    请求：path { agent_type }
    权限：agent:view
    返回：包含 registered 的 Agent 视图
    """
    row = await AgentDao.get_by_type(agent_type)
    if row is None:
        raise BizException(ErrCode.NOT_FOUND, f"Agent 未登记: {agent_type}")
    return success(_item(row, agent_type in _registered_types()))


@router.patch("/{agent_type}/enabled", summary="全局启停")
async def set_enabled(
    agent_type: str,
    body: EnabledIn,
    _: object = Depends(require_scope(Scope.AGENT_STATUS)),  # noqa: B008
    __: object = Depends(get_current_user),  # noqa: B008
):
    """全局启停 Agent，并同步运行时 registry。

    说明：库未登记但已注册时补登记；registry 未就绪则仅写库。
    请求：path { agent_type }, body { enabled: bool }
    权限：agent:status
    返回：{ agent_type, enabled }
    """
    row = await AgentDao.get_by_type(agent_type)
    if row is None:
        # 库未登记但该类型已注册时补登记，保证启停可持久化
        reg = app_state.agent_registry
        try:
            reg.get(agent_type)
        except (KeyError, AttributeError):
            raise BizException(ErrCode.NOT_FOUND, f"Agent 未登记: {agent_type}")  # noqa: B904
        name = agent_type
    else:
        name = row["name"]

    await AgentDao.upsert(agent_type, name=name, enabled=body.enabled)
    enabled = body.enabled

    # 同步运行时内存（registry 未就绪时仅写库）
    reg = app_state.agent_registry
    if reg is not None and agent_type in reg.list_types(only_enabled=False):
        reg.set_enabled(agent_type, enabled)
        try:
            meta = reg.get(agent_type)
            meta.db_enabled = enabled
        except KeyError:
            pass
    await publish_config_refresh("agent_registry")
    return success({"agent_type": agent_type, "enabled": enabled})


@router.get("/tenants/{tenant_id}/capabilities", summary="租户开通策略列表（分页）")
async def list_capabilities(
    tenant_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    _: object = Depends(require_scope(Scope.AGENT_LIST)),  # noqa: B008
    __: object = Depends(get_current_user),  # noqa: B008
) -> Any:
    """分页查询某租户的 Agent 开通策略列表。

    请求：path { tenant_id }, query { page, page_size }
    权限：agent:list
    返回：items(global_enabled/enabled/configured) / total / page / page_size
    """
    rows, total = await AgentDao.list_agents_paged(
        tenant_id=tenant_id, page=page, page_size=page_size
    )
    items = [
        {
            "agent_type": r["agent_type"],
            "name": r["name"],
            "global_enabled": r["enabled"],
            "enabled": r["tenant_enabled"],
            "configured": r["policy_configured"],
        }
        for r in rows
    ]
    return success({"items": items, "total": total, "page": page, "page_size": page_size})


@router.put("/tenants/{tenant_id}/capabilities", summary="设置租户开通策略")
async def set_capabilities(
    tenant_id: int,
    items: list[CapabilityIn],
    _: object = Depends(require_scope(Scope.AGENT_UPDATE)),
    __: object = Depends(get_current_user),  # noqa: B008
):
    """批量设置某租户的 Agent 开通策略并刷新运行时缓存。

    请求：path { tenant_id }, body { items: list[{agent_type, enabled}] }
    权限：agent:update
    返回：{ tenant_id, updated }
    """
    await AgentDao.set_policies(tenant_id, [(it.agent_type, it.enabled) for it in items])

    # 刷新运行时租户策略缓存
    reg = app_state.agent_registry
    if reg is not None:
        await reg.load_from_db()
    await publish_config_refresh("agent_registry")
    return success({"tenant_id": tenant_id, "updated": len(items)})


# ---------- Agent 元数据增删改 ----------


def _validate_input_schema(raw: Optional[str]) -> None:
    """input_schema 以 JSON 文本传入，落库前先校验合法性。"""
    if raw is None:
        return
    try:
        json.loads(raw)
    except (ValueError, TypeError):
        raise BizException(ErrCode.PARAM_ERROR, "input_schema 不是合法 JSON")  # noqa: B904


def _invalidate_llm_cache() -> None:
    """绑定关系变更后失效 per-agent LLM 缓存，使下次解析生效。"""
    factory = app_state.llm_factory
    if factory is not None:
        factory.clear_llm_cache()


async def _refresh_registry() -> None:
    reg = app_state.agent_registry
    if reg is not None:
        await reg.refresh()
    await publish_config_refresh("agent_registry")


@router.post("", summary="新增智能体")
async def create_agent(
    body: AgentIn,
    _: object = Depends(require_scope(Scope.AGENT_ADD)),  # noqa: B008
    __: object = Depends(get_current_user),  # noqa: B008
):
    """新增 Agent 元数据（agent_type 唯一）。

    请求：body { agent_type, name, description?, version, enabled, input_schema? }
    权限：agent:add
    返回：{ id, agent_type }
    """
    if await AgentDao.get_by_type(body.agent_type) is not None:
        raise BizException(ErrCode.PARAM_ERROR, f"agent_type 已存在: {body.agent_type}")
    _validate_input_schema(body.input_schema)
    new_id = await AgentDao.create(
        agent_type=body.agent_type,
        name=body.name,
        description=body.description or "",
        version=body.version,
        enabled=body.enabled,
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
    """更新 Agent 元数据。

    请求：path { agent_type }, body { name, description?, version, enabled, input_schema? }
    权限：agent:update
    返回：{ agent_type }
    """
    row = await AgentDao.get_by_type(agent_type)
    if row is None:
        raise BizException(ErrCode.NOT_FOUND, f"Agent 未登记: {agent_type}")
    _validate_input_schema(body.input_schema)
    await AgentDao.update(
        agent_type,
        name=body.name,
        description=body.description or "",
        version=body.version,
        enabled=body.enabled,
        input_schema=body.input_schema,
    )
    await _refresh_registry()
    return success({"agent_type": agent_type})


@router.delete("/{agent_type}", summary="删除智能体")
async def delete_agent(
    agent_type: str,
    _: object = Depends(require_scope(Scope.AGENT_DELETE)),  # noqa: B008
    __: object = Depends(get_current_user),  # noqa: B008
):
    """删除 Agent（有模型绑定时禁止）。

    说明：存在模型绑定需先到「配置」解绑。
    请求：path { agent_type }
    权限：agent:delete
    返回：{ agent_type }
    """
    row = await AgentDao.get_by_type(agent_type)
    if row is None:
        raise BizException(ErrCode.NOT_FOUND, f"Agent 未登记: {agent_type}")
    # 有模型绑定时禁止删除，要求先在「配置」中解绑
    if await AgentModelRelDao.count_by_agent(row["id"]) > 0:
        raise BizException(ErrCode.PARAM_ERROR, "该智能体已绑定模型，请先到「配置」解绑后再删除")
    await AgentDao.delete(agent_type)
    await _refresh_registry()
    return success({"agent_type": agent_type})


# ---------- 智能体 ↔ 模型绑定维护 ----------


@router.get("/{agent_type}/models", summary="智能体模型绑定列表（分页）")
async def list_agent_models(
    agent_type: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    _: object = Depends(require_scope(Scope.AGENT_VIEW)),  # noqa: B008
    __: object = Depends(get_current_user),  # noqa: B008
) -> Any:
    """分页查询 Agent 的模型绑定列表。

    请求：path { agent_type }, query { page, page_size }
    权限：agent:view
    返回：items / total / page / page_size
    """
    if await AgentDao.get_by_type(agent_type) is None:
        raise BizException(ErrCode.NOT_FOUND, f"Agent 未登记: {agent_type}")
    items, total = await AgentModelRelDao.list_by_agent_paged(agent_type, page, page_size)
    return success({"items": items, "total": total, "page": page, "page_size": page_size})


@router.post("/{agent_type}/models", summary="添加模型绑定")
async def add_agent_model(
    agent_type: str,
    body: AgentModelBindIn,
    _: object = Depends(require_scope(Scope.AGENT_UPDATE)),  # noqa: B008
    __: object = Depends(get_current_user),  # noqa: B008
):
    """为 Agent 添加模型绑定，默认项同类互斥。

    说明：is_default 为真时先清同 model_type 其他绑定默认标记；变更失效 LLM 缓存。
    请求：path { agent_type }, body { model_id, is_default?, priority? }
    权限：agent:update
    返回：{ agent_type, model_id }
    """
    row = await AgentDao.get_by_type(agent_type)
    if row is None:
        raise BizException(ErrCode.NOT_FOUND, f"Agent 未登记: {agent_type}")
    model = await ModelDao.get(body.model_id)
    if model is None:
        raise BizException(ErrCode.NOT_FOUND, f"模型不存在: {body.model_id}")
    agent_id = row["id"]
    if body.is_default:
        # 同类默认互斥：先清掉同 model_type 其他绑定的默认标记
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
    _: object = Depends(require_scope(Scope.AGENT_UPDATE)),  # noqa: B008
    __: object = Depends(get_current_user),  # noqa: B008
):
    """更新模型绑定的默认标记与优先级。

    说明：设为默认时同类互斥；变更失效 LLM 缓存；绑定不存在返回 404。
    请求：path { agent_type, model_id }, body { is_default?, priority? }
    权限：agent:update
    返回：{ agent_type, model_id }
    """
    row = await AgentDao.get_by_type(agent_type)
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
    _: object = Depends(require_scope(Scope.AGENT_DELETE)),  # noqa: B008
    __: object = Depends(get_current_user),  # noqa: B008
):
    """解绑 Agent 的模型（失效 LLM 缓存）。

    请求：path { agent_type, model_id }
    权限：agent:delete
    返回：{ agent_type, model_id }
    """
    row = await AgentDao.get_by_type(agent_type)
    if row is None:
        raise BizException(ErrCode.NOT_FOUND, f"Agent 未登记: {agent_type}")
    await AgentModelRelDao.remove(row["id"], model_id)
    _invalidate_llm_cache()
    return success({"agent_type": agent_type, "model_id": model_id})
