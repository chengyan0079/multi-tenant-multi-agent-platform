"""工具管理端点（租户级）：agent_tool CRUD + 启停 + 绑定租户。"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from backend.common.response import success
from backend.data.dao.agent.tool_dao import ToolDao
from backend.security.rbac import Scope
from backend.security.security import require_scope

router = APIRouter(prefix="/tools", tags=["admin"])


class ToolIn(BaseModel):
    tenant_id: int
    name: str = Field(..., min_length=1, max_length=64)
    plugin: str = Field("", max_length=64)
    description: str = ""
    schema: str = "{}"
    config: str = "{}"
    enabled: bool = True


class ToolUpdateIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    plugin: str = Field("", max_length=64)
    description: str = ""
    schema: str = "{}"
    config: str = "{}"
    enabled: bool = True


class EnabledIn(BaseModel):
    enabled: bool


class BindIn(BaseModel):
    tenant_id: int


@router.get("", summary="工具列表（租户级分页）")
async def list_tools(
    tenant_id: int = Query(..., description="租户ID"),
    name: Optional[str] = Query(None),
    enabled: Optional[bool] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    _=Depends(require_scope(Scope.TOOL_PAGE)),
):
    items, total = await ToolDao.list_paged(
        tenant_id=tenant_id, name=name, enabled=enabled, page=page, page_size=page_size
    )
    return success({"items": items, "total": total, "page": page, "page_size": page_size})


@router.get("/{tool_id}", summary="工具详情")
async def get_tool(tool_id: str, _=Depends(require_scope(Scope.TOOL_VIEW))):
    return success(await ToolDao.get(tool_id))


@router.post("", summary="新增工具")
async def create_tool(body: ToolIn, _=Depends(require_scope(Scope.TOOL_ADD))):
    tool_id = await ToolDao.create(
        tenant_id=body.tenant_id,
        name=body.name,
        plugin=body.plugin,
        description=body.description,
        schema=body.schema,
        config=body.config,
        enabled=body.enabled,
    )
    return success({"id": tool_id})


@router.put("/{tool_id}", summary="更新工具")
async def update_tool(
    tool_id: str, body: ToolUpdateIn, _=Depends(require_scope(Scope.TOOL_UPDATE))
):
    updated = await ToolDao.update(
        tool_id,
        name=body.name,
        plugin=body.plugin,
        description=body.description,
        schema=body.schema,
        config=body.config,
        enabled=body.enabled,
    )
    return success({"updated": updated})


@router.patch("/{tool_id}/enabled", summary="启停工具")
async def set_enabled(
    tool_id: str, body: EnabledIn, _=Depends(require_scope(Scope.TOOL_STATUS))
):
    return success({"updated": await ToolDao.set_enabled(tool_id, body.enabled)})


@router.delete("/{tool_id}", summary="删除工具")
async def delete_tool(tool_id: str, _=Depends(require_scope(Scope.TOOL_DELETE))):
    return success({"deleted": await ToolDao.delete(tool_id)})


@router.get("/{tool_id}/tenants", summary="工具已绑定租户")
async def list_tool_tenants(tool_id: str, _=Depends(require_scope(Scope.TOOL_VIEW))):
    row = await ToolDao.get(tool_id)
    if not row:
        return success([])
    return success(await ToolDao.list_tenants(row["name"]))


@router.post("/{tool_id}/tenants", summary="绑定到租户")
async def bind_tenant(
    tool_id: str, body: BindIn, _=Depends(require_scope(Scope.TOOL_UPDATE))
):
    await ToolDao.bind_tenant(tool_id, body.tenant_id)
    return success({"bound": body.tenant_id})
