"""工具与插件管理端点（/api/v1/admin/plugins）。"""
from __future__ import annotations

import json
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from backend.broker.publish import publish_config_refresh
from backend.common.response import success
from backend.data.dao.agent.plugin_dao import PluginDao
from backend.data.dao.auth.tenant_dao import TenantDao
from backend.data.dao.auth.user_dao import UserDao
from backend.middleware.auth import get_current_user
from backend.observability.exception import BizException, ErrCode
from backend.security.rbac import Scope
from backend.security.security import require_scope
from backend.server.managers.plugin_manager import reload_plugins

router = APIRouter(prefix="/plugins", tags=["admin"])

_STATUSES = ("enabled", "disabled")


async def _refresh_registry() -> None:
    await reload_plugins()
    await publish_config_refresh("plugin_registry")


class PluginIn(BaseModel):
    name: str = Field(..., max_length=64)
    version: str = Field(..., max_length=32)
    capabilities: str
    config: str
    status: str = Field("enabled", max_length=32)
    tenant_id: int
    user_id: int


class PluginStatusIn(BaseModel):
    status: str = Field(..., max_length=32)


def _validate(body: PluginIn) -> None:
    for field in ("capabilities", "config"):
        try:
            json.loads(getattr(body, field))
        except (TypeError, ValueError) as exc:
            raise BizException(ErrCode.PARAM_ERROR, f"{field} 不是合法 JSON: {exc}") from exc
    if body.status not in _STATUSES:
        raise BizException(ErrCode.PARAM_ERROR, f"status 仅支持 {_STATUSES}")


def _parse_id(plugin_id: str) -> str:
    try:
        return str(UUID(plugin_id))
    except ValueError as exc:
        raise BizException(ErrCode.PARAM_ERROR, "插件 ID 不是合法 UUID") from exc


async def _check_refs(tenant_id: int, user_id: int) -> None:
    if await TenantDao.get(tenant_id) is None:
        raise BizException(ErrCode.NOT_FOUND, f"租户不存在: {tenant_id}")
    if await UserDao.get(user_id) is None:
        raise BizException(ErrCode.NOT_FOUND, f"用户不存在: {user_id}")


@router.get("", summary="插件列表（分页）")
async def list_plugins(
    name: Optional[str] = Query(None, description="按插件名模糊匹配"),
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    _: object = Depends(require_scope(Scope.TOOL_PAGE)),  # noqa: B008
    __: object = Depends(get_current_user),  # noqa: B008
) -> Any:
    rows, total = await PluginDao.list_paged(
        name=name, status=status, page=page, page_size=page_size
    )
    return success({"items": rows, "total": total, "page": page, "page_size": page_size})


@router.get("/{plugin_id}", summary="插件详情")
async def get_plugin(
    plugin_id: str,
    _: object = Depends(require_scope(Scope.TOOL_VIEW)),  # noqa: B008
    __: object = Depends(get_current_user),  # noqa: B008
) -> Any:
    row = await PluginDao.get(_parse_id(plugin_id))
    if row is None:
        raise BizException(ErrCode.NOT_FOUND, "插件不存在")
    return success(row)


@router.post("", summary="新增插件")
async def create_plugin(
    body: PluginIn,
    _: object = Depends(require_scope(Scope.TOOL_ADD)),  # noqa: B008
    __: object = Depends(get_current_user),  # noqa: B008
) -> Any:
    _validate(body)
    await _check_refs(body.tenant_id, body.user_id)
    if await PluginDao.name_exists(body.name):
        raise BizException(ErrCode.PARAM_ERROR, f"插件名已存在: {body.name}")
    plugin_id = await PluginDao.create(**body.model_dump())
    await _refresh_registry()
    return success({"id": plugin_id})


@router.put("/{plugin_id}", summary="更新插件")
async def update_plugin(
    plugin_id: str,
    body: PluginIn,
    _: object = Depends(require_scope(Scope.TOOL_UPDATE)),  # noqa: B008
    __: object = Depends(get_current_user),  # noqa: B008
) -> Any:
    pid = _parse_id(plugin_id)
    _validate(body)
    await _check_refs(body.tenant_id, body.user_id)
    if await PluginDao.get(pid) is None:
        raise BizException(ErrCode.NOT_FOUND, "插件不存在")
    if await PluginDao.name_exists(body.name, exclude_id=pid):
        raise BizException(ErrCode.PARAM_ERROR, f"插件名已存在: {body.name}")
    data = body.model_dump()
    data.pop("name")
    data.pop("tenant_id")
    await PluginDao.update(pid, **data)
    await _refresh_registry()
    return success({"id": pid})


@router.delete("/{plugin_id}", summary="删除插件")
async def delete_plugin(
    plugin_id: str,
    _: object = Depends(require_scope(Scope.TOOL_DELETE)),  # noqa: B008
    __: object = Depends(get_current_user),  # noqa: B008
) -> Any:
    pid = _parse_id(plugin_id)
    if await PluginDao.get(pid) is None:
        raise BizException(ErrCode.NOT_FOUND, "插件不存在")
    await PluginDao.delete(pid)
    await _refresh_registry()
    return success({"id": pid})


@router.patch("/{plugin_id}/status", summary="插件启停")
async def set_status(
    plugin_id: str,
    body: PluginStatusIn,
    _: object = Depends(require_scope(Scope.TOOL_STATUS)),  # noqa: B008
    __: object = Depends(get_current_user),  # noqa: B008
) -> Any:
    pid = _parse_id(plugin_id)
    if body.status not in _STATUSES:
        raise BizException(ErrCode.PARAM_ERROR, f"status 仅支持 {_STATUSES}")
    if await PluginDao.get(pid) is None:
        raise BizException(ErrCode.NOT_FOUND, "插件不存在")
    await PluginDao.set_status(pid, body.status)
    await _refresh_registry()
    return success({"id": pid, "status": body.status})
