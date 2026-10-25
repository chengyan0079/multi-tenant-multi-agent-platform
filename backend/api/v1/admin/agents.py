"""Agent 管理端点（超管）：元数据目录 + 全局启停 + 租户级开通策略。

挂在 /api/v1/admin/agents 下，鉴权由装配处统一挂 require_super_admin()。

数据来源：
- `agent` 表：可持久化的元数据（展示名 / 描述 / 输入 schema / 全局开关 / 版本）；
- `AgentRegistry`（app_state）：代码注册的图构造器，运行时同步启停状态。

说明：Agent 是否可用 = 全局开关（agent.enabled）AND 租户策略
（agent_capability_policy，未配置视为开通）；启停写库后同步刷新 registry 内存。
"""
from __future__ import annotations

from typing import Any, Optional

from typing import Any, Optional

from fastapi import APIRouter, Depends, Query

from backend.api.v1.admin.schemas import CapabilityIn, EnabledIn
from backend.app_state import app_state
from backend.common.response import success
from backend.observability.exception import BizException, ErrCode
from backend.data.dao.agent.agent_dao import AgentDao
from backend.middleware.auth import get_current_user

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
    _: object = Depends(get_current_user),  # noqa: B008
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
async def get_agent(agent_type: str, _: object = Depends(get_current_user)):  # noqa: B008
    row = await AgentDao.get_by_type(agent_type)
    if row is None:
        raise BizException(ErrCode.NOT_FOUND, f"Agent 未登记: {agent_type}")
    return success(_item(row, agent_type in _registered_types()))


@router.patch("/{agent_type}/enabled", summary="全局启停")
async def set_enabled(
    agent_type: str, body: EnabledIn, _: object = Depends(get_current_user),  # noqa: B008
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
    tenant_id: int, _: object = Depends(get_current_user),  # noqa: B008
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
    tenant_id: int, items: list[CapabilityIn], _: object = Depends(get_current_user),  # noqa: B008
):
    await AgentDao.set_policies(
        tenant_id, [(it.agent_type, it.enabled) for it in items]
    )

    # 刷新运行时租户策略缓存
    reg = app_state.agent_registry
    if reg is not None:
        await reg.load_from_db()
    return success({"tenant_id": tenant_id, "updated": len(items)})
