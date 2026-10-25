"""租户管理员用户端点（/api/v1/tenant/users）。

租户取自 token（require_tenant 已注入），body 不接受 tenant_id。可创建/改角色/解绑本租户用户，
角色仅限 student / teacher；管理员（tenant_admin）的更换只归超管（PUT /admin/tenants/{id}/manager）。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from backend.api.v1.tenant.schemas import TenantUserIn, TenantUserRoleIn
from backend.common.response import success
from backend.observability.exception import BizException, ErrCode
from backend.data.dao.ops.audit_dao import AuditDao
from backend.data.dao.auth.rbac_dao import RbacDao
from backend.data.dao.auth.user_dao import UserDao
from backend.middleware.auth import CurrentUser, get_current_user
from backend.security.rbac import RoleName
from backend.security.security import require_scope, require_tenant_admin

router = APIRouter(prefix="/users", tags=["tenant"])

_ASSIGNABLE = (RoleName.STUDENT.value, RoleName.TEACHER.value)


@router.get("", summary="本租户用户列表")
async def list_users(
    current: CurrentUser = Depends(get_current_user),  # noqa: B008
    _: object = Depends(require_tenant_admin()),  # noqa: B008
    __: object = Depends(require_scope("rbac:read")),  # noqa: B008
) -> Any:
    rows = await RbacDao.list_tenant_members(current.tenant_id)
    return success({"items": rows, "total": len(rows)})


@router.post("", summary="本租户建普通用户")
async def create_user(
    body: TenantUserIn,
    current: CurrentUser = Depends(get_current_user),  # noqa: B008
    _: object = Depends(require_tenant_admin()),  # noqa: B008
    __: object = Depends(require_scope("rbac:write")),  # noqa: B008
) -> Any:
    if body.role not in _ASSIGNABLE:
        raise BizException(ErrCode.PARAM_ERROR, "本租户仅可创建 student / teacher")
    if await UserDao.get_by_username(body.username) is not None:
        raise BizException(ErrCode.PARAM_ERROR, "登录名已存在")
    role_id = await RbacDao.get_role_id(body.role)
    new_id = await UserDao.create(
        username=body.username,
        name=body.name,
        password=body.password,
        tenant_id=current.tenant_id,
    )
    await RbacDao.assign_role(new_id, current.tenant_id, role_id)
    await AuditDao.write(
        tenant_id=current.tenant_id, user_id=current.user_id,
        action="rbac.grant", target=str(new_id), detail=f"本租户建用户 role={body.role}",
    )
    return success({"id": new_id})


@router.put("/{user_id}/role", summary="改本租户内角色（仅 student/teacher）")
async def change_role(
    user_id: int,
    body: TenantUserRoleIn,
    current: CurrentUser = Depends(get_current_user),  # noqa: B008
    _: object = Depends(require_tenant_admin()),  # noqa: B008
    __: object = Depends(require_scope("rbac:write")),  # noqa: B008
) -> Any:
    if body.role not in _ASSIGNABLE:
        raise BizException(ErrCode.PARAM_ERROR, "本租户仅可分配 student / teacher")
    membership = await RbacDao.get_membership(user_id, current.tenant_id)
    if membership is None:
        raise BizException(ErrCode.NOT_FOUND, "该用户不在本租户")
    if membership == RoleName.TENANT_ADMIN.value:
        raise BizException(ErrCode.FORBIDDEN, "租户管理员不可改角色，需由超管更换")
    role_id = await RbacDao.get_role_id(body.role)
    await RbacDao.assign_role(user_id, current.tenant_id, role_id)
    await AuditDao.write(
        tenant_id=current.tenant_id, user_id=current.user_id,
        action="rbac.grant", target=str(user_id), detail=f"角色={body.role}",
    )
    return success({"user_id": user_id, "role": body.role})


@router.delete("/{user_id}", summary="从本租户解绑用户")
async def delete_user(
    user_id: int,
    current: CurrentUser = Depends(get_current_user),  # noqa: B008
    _: object = Depends(require_tenant_admin()),  # noqa: B008
    __: object = Depends(require_scope("rbac:write")),  # noqa: B008
) -> Any:
    if user_id == current.user_id:
        raise BizException(ErrCode.FORBIDDEN, "不能解绑自己")
    membership = await RbacDao.get_membership(user_id, current.tenant_id)
    if membership is None:
        raise BizException(ErrCode.NOT_FOUND, "该用户不在本租户")
    if membership == RoleName.TENANT_ADMIN.value:
        raise BizException(
            ErrCode.FORBIDDEN, "租户管理员不可删除，请先更换", http_status=409
        )
    removed = await RbacDao.delete_membership(user_id, current.tenant_id)
    await AuditDao.write(
        tenant_id=current.tenant_id, user_id=current.user_id,
        action="rbac.revoke", target=str(user_id), detail="从本租户解绑",
    )
    return success({"user_id": user_id, "removed": removed})
