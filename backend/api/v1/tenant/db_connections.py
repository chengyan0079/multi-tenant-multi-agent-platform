"""租户数据库连接管理（db-connections）：CRUD + 启停 + 测试连接。"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from backend.common.response import success
from backend.data.dao.agent.db_connection_dao import DbConnectionDao
from backend.middleware.auth import CurrentUser, get_current_user
from backend.observability.exception import BizException, ErrCode
from backend.security.rbac import Scope
from backend.security.security import require_scope
from backend.services.db_connection_service import fetch_metadata

router = APIRouter(prefix="/db-connections", tags=["tenant"])


class DbConnIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    db_type: str = Field(..., pattern="^(mysql|postgresql)$")
    host: str = Field(..., min_length=1, max_length=255)
    port: int = Field(..., ge=1, le=65535)
    username: str = Field(..., min_length=1, max_length=128)
    password: str = Field(..., max_length=512)
    database: str = Field(..., min_length=1, max_length=128)
    schema_name: Optional[str] = Field(None, max_length=128)
    readonly: bool = True
    enabled: bool = True
    remark: Optional[str] = None


class EnabledIn(BaseModel):
    enabled: bool


def _mask(row: dict) -> dict:
    """出参脱敏：不返回密码。"""
    out = dict(row)
    out.pop("password", None)
    return out


@router.get("", summary="数据源列表")
async def list_connections(
    name: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    current: CurrentUser = Depends(get_current_user),
    _: object = Depends(require_scope(Scope.DB_CONNECTION_PAGE)),
):
    rows, total = await DbConnectionDao.list_paged(
        tenant_id=current.tenant_id, name=name, page=page, page_size=page_size
    )
    return success(
        {
            "items": [_mask(r) for r in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    )


@router.get("/{connection_id}", summary="数据源详情")
async def get_connection(
    connection_id: str,
    current: CurrentUser = Depends(get_current_user),
    _: object = Depends(require_scope(Scope.DB_CONNECTION_VIEW)),
):
    row = await DbConnectionDao.get(current.tenant_id, connection_id)
    if row is None:
        raise BizException(ErrCode.NOT_FOUND, "数据源不存在")
    return success(_mask(row))


@router.post("", summary="新增数据源")
async def create_connection(
    body: DbConnIn,
    current: CurrentUser = Depends(get_current_user),
    _: object = Depends(require_scope(Scope.DB_CONNECTION_ADD)),
):
    new_id = await DbConnectionDao.create(tenant_id=current.tenant_id, **body.model_dump())
    return success({"id": new_id})


@router.put("/{connection_id}", summary="更新数据源")
async def update_connection(
    connection_id: str,
    body: DbConnIn,
    current: CurrentUser = Depends(get_current_user),
    _: object = Depends(require_scope(Scope.DB_CONNECTION_UPDATE)),
):
    if await DbConnectionDao.get(current.tenant_id, connection_id) is None:
        raise BizException(ErrCode.NOT_FOUND, "数据源不存在")
    updated = await DbConnectionDao.update(
        current.tenant_id, connection_id, **body.model_dump()
    )
    return success({"updated": updated})


@router.patch("/{connection_id}/enabled", summary="启停数据源")
async def set_enabled(
    connection_id: str,
    body: EnabledIn,
    current: CurrentUser = Depends(get_current_user),
    _: object = Depends(require_scope(Scope.DB_CONNECTION_STATUS)),
):
    return success(
        {
            "updated": await DbConnectionDao.set_enabled(
                current.tenant_id, connection_id, body.enabled
            )
        }
    )


@router.delete("/{connection_id}", summary="删除数据源")
async def delete_connection(
    connection_id: str,
    current: CurrentUser = Depends(get_current_user),
    _: object = Depends(require_scope(Scope.DB_CONNECTION_DELETE)),
):
    return success(
        {"deleted": await DbConnectionDao.delete(current.tenant_id, connection_id)}
    )


@router.post("/{connection_id}/test", summary="测试连接")
async def test_connection(
    connection_id: str,
    current: CurrentUser = Depends(get_current_user),
    _: object = Depends(require_scope(Scope.DB_CONNECTION_VIEW)),
):
    result = await fetch_metadata(current.tenant_id, connection_id, [])
    return success({"ok": bool(result.get("ok")), "error": result.get("error")})
