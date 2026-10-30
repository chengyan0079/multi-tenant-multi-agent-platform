"""租户管理员角色端点（/api/v1/tenant/roles）。

返回本租户管理员可分配的角色（student / teacher）。租户管理员不可分配 tenant_admin，
那属于超管的「更换管理员」职责（PUT /admin/tenants/{id}/manager）。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from backend.common.response import success
from backend.data.dao.auth.rbac_dao import RbacDao
from backend.middleware.auth import CurrentUser, get_current_user
from backend.security.rbac import RoleName, Scope
from backend.security.security import require_scope, require_tenant_admin

router = APIRouter(prefix="/roles", tags=["tenant"])


@router.get("", summary="本租户可分配角色（分页）")
async def list_roles(
    current: CurrentUser = Depends(get_current_user),  # noqa: B008
    _: object = Depends(require_tenant_admin()),  # noqa: B008
    __: object = Depends(require_scope(Scope.RBAC_PAGE)),  # noqa: B008
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
) -> Any:
    rows = await RbacDao.list_roles_with_permissions()
    items = [
        {"role": r["name"], "description": r.get("description")}
        for r in rows
        if r["name"] not in (RoleName.ADMIN.value, RoleName.TENANT_ADMIN.value)
    ]
    total = len(items)
    start = (page - 1) * page_size
    paged = items[start : start + page_size]
    return success({"items": paged, "total": total, "page": page, "page_size": page_size})
