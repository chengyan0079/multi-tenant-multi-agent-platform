"""超管审计日志端点（/api/v1/admin/audit）。

超管可查全量，也可传 tenant_id 过滤某个租户；审计日志只读、无写接口（§6.5）。
三种审计：业务审计 / 登录日志 / API 调用日志，分别走不同表与端点。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from backend.common.response import success
from backend.data.dao.ops.audit_dao import AuditDao
from backend.data.dao.auth.login_log_dao import LoginLogDao
from backend.data.dao.ops.api_log_dao import ApiLogDao
from backend.middleware.auth import CurrentUser, get_current_user
from backend.observability.exception import BizException, ErrCode
from backend.security.rbac import Scope
from backend.security.security import require_scope

router = APIRouter(prefix="/audit", tags=["admin"])


@router.get("/logs", summary="业务审计日志（可筛租户，分页）")
async def audit_logs(
    tenant_id: int | None = Query(None, description="不传查全量（仅超管）"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    _: object = Depends(require_scope(Scope.AUDIT_PAGE)),  # noqa: B008
    __: object = Depends(get_current_user),  # noqa: B008
) -> Any:
    rows, total = await AuditDao.query(tenant_id=tenant_id, page=page, page_size=page_size)
    return success({"items": rows, "total": total, "page": page, "page_size": page_size})


@router.get("/logs/{log_id}", summary="业务审计日志详情")
async def audit_log_detail(
    log_id: str,
    _: object = Depends(require_scope(Scope.AUDIT_VIEW)),  # noqa: B008
    __: object = Depends(get_current_user),  # noqa: B008
) -> Any:
    row = await AuditDao.get(log_id)
    if row is None:
        raise BizException(ErrCode.NOT_FOUND, f"审计记录不存在: {log_id}")
    return success(row)


@router.get("/login-logs", summary="登录日志（可筛租户，分页）")
async def login_logs(
    tenant_id: int | None = Query(None, description="不传查全量（仅超管）"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    _: object = Depends(require_scope(Scope.AUDIT_PAGE)),  # noqa: B008
    __: object = Depends(get_current_user),  # noqa: B008
) -> Any:
    rows, total = await LoginLogDao.query(tenant_id=tenant_id, page=page, page_size=page_size)
    return success({"items": rows, "total": total, "page": page, "page_size": page_size})


@router.get("/api-logs", summary="API 调用日志（可筛租户，分页）")
async def api_logs(
    tenant_id: int | None = Query(None, description="不传查全量（仅超管）"),
    path_prefix: str | None = Query(None, description="路径前缀，如 /api/v1/tenant/"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    _: object = Depends(require_scope(Scope.AUDIT_PAGE)),  # noqa: B008
    __: object = Depends(get_current_user),  # noqa: B008
) -> Any:
    rows, total = await ApiLogDao.query(
        tenant_id=tenant_id,
        page=page,
        page_size=page_size,
        path_prefix=path_prefix,
    )
    return success({"items": rows, "total": total, "page": page, "page_size": page_size})
