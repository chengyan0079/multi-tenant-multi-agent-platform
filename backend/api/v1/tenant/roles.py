"""租户管理员角色端点：返回本租户可分配角色（排除 admin/tenant_admin）。"""

from __future__ import annotations

from typing import Any, List

from fastapi import APIRouter, Depends

from backend.common.response import ApiResponse, success
from backend.data.dao.auth.rbac_dao import RbacDao
from backend.middleware.auth import CurrentUser, get_current_user
from backend.security.rbac import RoleName, Scope
from backend.security.security import require_scope

router = APIRouter(prefix="/roles", tags=["tenant"])


async def _assignable_roles() -> set[str]:
    """本租户管理员可分配的角色（排除固定角色 admin/tenant_admin），由库驱动。"""
    rows = await RbacDao.list_roles_with_permissions()
    return {
        r["name"]
        for r in rows
        if r["name"] not in (RoleName.ADMIN.value, RoleName.TENANT_ADMIN.value)
    }


@router.get(
    "",
    summary="本租户可分配角色列表（排除 admin/tenant_admin）",
    response_model=ApiResponse[List[str]],
)
async def list_assignable_roles(
    current: CurrentUser = Depends(get_current_user),  # noqa: B008
    __: object = Depends(require_scope(Scope.USER_PAGE)),  # noqa: B008
) -> Any:
    """返回本租户管理员可分配的角色名列表（排除固定角色）。

    请求：无
    权限：user:page
    返回：角色名有序列表
    """
    roles = await _assignable_roles()
    return success(sorted(roles))
