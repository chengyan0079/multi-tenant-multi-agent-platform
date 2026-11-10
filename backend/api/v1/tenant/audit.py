"""租户管理员审计端点：本租户审计日志分页（tenant_id 强制取 token）。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from backend.common.response import success
from backend.data.dao.ops.audit_dao import AuditDao
from backend.middleware.auth import CurrentUser, get_current_user
from backend.security.rbac import Scope
from backend.security.security import require_scope

router = APIRouter(prefix="/audit", tags=["tenant"])


@router.get("/logs", summary="本租户审计日志（分页）")
async def audit_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    current: CurrentUser = Depends(get_current_user),  # noqa: B008
    __: object = Depends(require_scope(Scope.AUDIT_PAGE)),  # noqa: B008
) -> Any:
    """本租户业务审计日志分页查询（tenant_id 强制取当前用户，前端无法越权）。

    请求：query { page, page_size }
    权限：audit:page
    返回：items / total / page / page_size
    """
    rows, total = await AuditDao.query(tenant_id=current.tenant_id, page=page, page_size=page_size)
    return success({"items": rows, "total": total, "page": page, "page_size": page_size})
