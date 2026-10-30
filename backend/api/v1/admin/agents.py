"""Agent 管理端点（超管）：元数据目录 + 全局启停 + 租户级开通策略。

挂在 /api/v1/admin/agents 下，鉴权由装配处统一挂 require_super_admin()。

数据来源：
- `agent` 表：可持久化的元数据（展示名 / 描述 / 输入 schema / 全局开关 / 版本）；
- `AgentRegistry`（app_state）：代码注册的图构造器，运行时同步启停状态。

说明：Agent 是否可用 = 全局开关（agent.enabled）AND 租户策略
（agent_capability_policy，未配置视为开通）；启停写库后同步刷新 registry 内存。
"""
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


@router.get("", summary="Agent 列表")
async def list_agents(
    tenant_id: Optional[int] = Query(None, description="传则附带该租户的开通状态"),
    only_enabled: bool = Query(False, description="仅返回全局启用且已注册的"),
    _: object = Depends(require_scope(Scope.AGENT_LIST)),  # noqa: B008
    __: object = Depends(get_current_user),  # noqa: B008
):
    rows = await AgentDao.list_agents()
    policies: dict[str, bool] = {}
    if tenant_id is not None:
        policies = {
            p["agent_type"]: p["enabled"]
            for p in await AgentDao.list_policies(tenant_id)
        }
    registered = _registered_types()
    items = []
    for r in rows:
        if only_enabled and (not r["enabled"] or r["agent_type"] not in registered):
            continue
        item = _item(r, r["agent_type"] in registered)
        if tenant_id is not None:
            # 未配置策略视为开通
            item["tenant_enabled"] = policies.get(r["agent_type"], True)
        items.append(item)
    return success({"items": items, "total": len(items)})


@router.get("/{agent_type}", summary="Agent 详情")
async def get_agent(agent_type: str, _: object = Depends(require_scope(Scope.AGENT_VIEW)), __: object = Depends(get_current_user)):  # noqa: B008
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
    return success({"agent_type": agent_type, "enabled": enabled})


@router.get("/tenants/{tenant_id}/capabilities", summary="租户开通策略列表")
async def list_capabilities(
    tenant_id: int, _: object = Depends(require_scope(Scope.AGENT_LIST)), __: object = Depends(get_current_user),  # noqa: B008
):
    agents = await AgentDao.list_agents()
    policy_map = {
        p["agent_type"]: p["enabled"] for p in await AgentDao.list_policies(tenant_id)
    }
    items = [{
        "agent_type": a["agent_type"],
        "name": a["name"],
        "global_enabled": a["enabled"],
        "enabled": policy_map.get(a["agent_type"], True),
        "configured": a["agent_type"] in policy_map,
    } for a in agents]
    return success({"items": items, "total": len(items)})


@router.put("/tenants/{tenant_id}/capabilities", summary="设置租户开通策略")
async def set_capabilities(
    tenant_id: int, items: list[CapabilityIn], _: object = Depends(require_scope(Scope.AGENT_UPDATE)), __: object = Depends(get_current_user),  # noqa: B008
):
    await AgentDao.set_policies(
        tenant_id, [(it.agent_type, it.enabled) for it in items]
    )

    # 刷新运行时租户策略缓存
    reg = app_state.agent_registry
    if reg is not None:
        await reg.load_from_db()
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


@router.post("", summary="新增智能体")
async def create_agent(
    body: AgentIn,
    _: object = Depends(require_scope(Scope.AGENT_ADD)),  # noqa: B008
    __: object = Depends(get_current_user),  # noqa: B008
):
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
    return success({"id": new_id, "agent_type": body.agent_type})


@router.put("/{agent_type}", summary="更新智能体")
async def update_agent(
    agent_type: str,
    body: AgentIn,
    _: object = Depends(require_scope(Scope.AGENT_UPDATE)),  # noqa: B008
    __: object = Depends(get_current_user),  # noqa: B008
):
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
    return success({"agent_type": agent_type})


@router.delete("/{agent_type}", summary="删除智能体")
async def delete_agent(
    agent_type: str,
    _: object = Depends(require_scope(Scope.AGENT_DELETE)),  # noqa: B008
    __: object = Depends(get_current_user),  # noqa: B008
):
    row = await AgentDao.get_by_type(agent_type)
    if row is None:
        raise BizException(ErrCode.NOT_FOUND, f"Agent 未登记: {agent_type}")
    # 有模型绑定时禁止删除，要求先在「配置」中解绑
    if await AgentModelRelDao.count_by_agent(row["id"]) > 0:
        raise BizException(ErrCode.PARAM_ERROR, "该智能体已绑定模型，请先到「配置」解绑后再删除")
    await AgentDao.delete(agent_type)
    return success({"agent_type": agent_type})


# ---------- 智能体 ↔ 模型绑定维护 ----------


@router.get("/{agent_type}/models", summary="智能体模型绑定列表")
async def list_agent_models(
    agent_type: str,
    _: object = Depends(require_scope(Scope.AGENT_VIEW)),  # noqa: B008
    __: object = Depends(get_current_user),  # noqa: B008
):
    if await AgentDao.get_by_type(agent_type) is None:
        raise BizException(ErrCode.NOT_FOUND, f"Agent 未登记: {agent_type}")
    items = await AgentModelRelDao.list_by_agent(agent_type)
    return success({"items": items, "total": len(items)})


@router.post("/{agent_type}/models", summary="添加模型绑定")
async def add_agent_model(
    agent_type: str,
    body: AgentModelBindIn,
    _: object = Depends(require_scope(Scope.AGENT_UPDATE)),  # noqa: B008
    __: object = Depends(get_current_user),  # noqa: B008
):
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
    row = await AgentDao.get_by_type(agent_type)
    if row is None:
        raise BizException(ErrCode.NOT_FOUND, f"Agent 未登记: {agent_type}")
    await AgentModelRelDao.remove(row["id"], model_id)
    _invalidate_llm_cache()
    return success({"agent_type": agent_type, "model_id": model_id})
