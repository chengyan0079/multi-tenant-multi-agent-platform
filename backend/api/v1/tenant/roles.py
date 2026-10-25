"""租户管理员角色端点（/api/v1/tenant/roles）。

返回本租户管理员可分配的角色（student / teacher）。租户管理员不可分配 tenant_admin，
那属于超管的「更换管理员」职责（PUT /admin/tenants/{id}/manager）。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from backend.common.response import success
from backend.middleware.auth import CurrentUser, get_current_user
from backend.security.security import require_scope, require_tenant_admin

router = APIRouter(prefix="/roles", tags=["tenant"])


@router.get("", summary="本租户可分配角色")
async def list_roles(
    current: CurrentUser = Depends(get_current_user),  # noqa: B008
    _: object = Depends(require_tenant_admin()),  # noqa: B008
    __: object = Depends(require_scope("rbac:read")),  # noqa: B008
) -> Any:
    return success({"items": [{"role": "student"}, {"role": "teacher"}], "total": 2})
