"""超管审计日志端点：业务审计 / 登录日志 / API 调用日志（只读，可按租户过滤）。"""

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
    """业务审计日志分页查询（超管可传 tenant_id 过滤）。

    请求：query { tenant_id?, page, page_size }
    权限：audit:page
    返回：items / total / page / page_size
    """
    rows, total = await AuditDao.query(tenant_id=tenant_id, page=page, page_size=page_size)
    return success({"items": rows, "total": total, "page": page, "page_size": page_size})


@router.get("/logs/{log_id}", summary="业务审计日志详情")
async def audit_log_detail(
    log_id: str,
    _: object = Depends(require_scope(Scope.AUDIT_VIEW)),  # noqa: B008
    __: object = Depends(get_current_user),  # noqa: B008
) -> Any:
    """业务审计日志详情。

    请求：path { log_id }
    权限：audit:view
    返回：单条审计记录
    """
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
    """登录日志分页查询（超管可传 tenant_id 过滤）。

    请求：query { tenant_id?, page, page_size }
    权限：audit:page
    返回：items / total / page / page_size
    """
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
    """API 调用日志分页查询（可按路径前缀过滤）。

    请求：query { tenant_id?, path_prefix?, page, page_size }
    权限：audit:page
    返回：items / total / page / page_size
    """
    rows, total = await ApiLogDao.query(
        tenant_id=tenant_id,
        page=page,
        page_size=page_size,
        path_prefix=path_prefix,
    )
    return success({"items": rows, "total": total, "page": page, "page_size": page_size})
