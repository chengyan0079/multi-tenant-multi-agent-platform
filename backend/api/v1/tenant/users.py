"""租户管理员用户端点：本租户用户列表/创建/改角色/解绑/详情（tenant_id 取自 token）。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from backend.api.v1.tenant.roles import _assignable_roles
from backend.api.v1.tenant.schemas import Paged, UserItem, TenantUserIn, TenantUserRoleIn
from backend.common.response import ApiResponse, success
from backend.observability.exception import BizException, ErrCode
from backend.data.dao.ops.audit_dao import AuditDao
from backend.data.dao.auth.rbac_dao import RbacDao
from backend.data.dao.auth.user_dao import UserDao
from backend.middleware.auth import CurrentUser, get_current_user
from backend.security.rbac import RoleName, Scope
from backend.security.security import require_scope

router = APIRouter(prefix="/users", tags=["tenant"])


@router.get(
    "",
    summary="本租户用户列表（分页）",
    response_model=ApiResponse[Paged[UserItem]],
)
async def list_users(
    current: CurrentUser = Depends(get_current_user),  # noqa: B008
    __: object = Depends(require_scope(Scope.USER_PAGE)),  # noqa: B008
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    username: str | None = Query(None, description="登录名模糊匹配"),
    created_from: str | None = Query(None, description="创建日期起，格式 yyyy-MM-dd"),
    created_to: str | None = Query(None, description="创建日期止，格式 yyyy-MM-dd"),
) -> Any:
    """本租户用户列表分页查询（名称/创建日期过滤，密码不外露）。

    请求：query { page, page_size, username?, created_from?, created_to? }
    权限：user:page
    返回：items / total / page / page_size
    """
    rows, total = await RbacDao.list_tenant_members(
        current.tenant_id,
        username=username,
        created_from=created_from,
        created_to=created_to,
        page=page,
        page_size=page_size,
    )
    items = [
        {
            "id": r["id"],
            "username": r["username"],
            "name": r["name"],
            "tenant_id": r["tenant_id"],
            "role": r["role_name"],
            "create_at": r["create_at"],
            "updated_at": r["updated_at"],
        }
        for r in rows
    ]
    return success({"items": items, "total": total, "page": page, "page_size": page_size})


@router.post("", summary="本租户建普通用户")
async def create_user(
    body: TenantUserIn,
    current: CurrentUser = Depends(get_current_user),  # noqa: B008
    __: object = Depends(require_scope(Scope.USER_ADD)),  # noqa: B008
) -> Any:
    """在本租户创建普通用户并绑定角色（写审计日志）。

    请求：body { username, name, password, role? }
    权限：user:add
    返回：{ id }
    """
    if body.role not in await _assignable_roles():
        raise BizException(ErrCode.PARAM_ERROR, "本租户仅可创建普通角色（非 admin/tenant_admin）")
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
        tenant_id=current.tenant_id,
        user_id=current.user_id,
        action="rbac.grant",
        target=str(new_id),
        detail=f"本租户建用户 role={body.role}",
    )
    return success({"id": new_id})


@router.put("/{user_id}/role", summary="改本租户内角色（仅 student/teacher）")
async def change_role(
    user_id: int,
    body: TenantUserRoleIn,
    current: CurrentUser = Depends(get_current_user),  # noqa: B008
    __: object = Depends(require_scope(Scope.USER_UPDATE)),  # noqa: B008
) -> Any:
    """改本租户内用户角色（仅 student/teacher，写审计日志）。

    请求：path { user_id }, body { role }
    权限：user:update
    返回：{ user_id, role }
    """
    if body.role not in await _assignable_roles():
        raise BizException(ErrCode.PARAM_ERROR, "本租户仅可分配普通角色（非 admin/tenant_admin）")
    membership = await RbacDao.get_membership(user_id, current.tenant_id)
    if membership is None:
        raise BizException(ErrCode.NOT_FOUND, "该用户不在本租户")
    if membership == RoleName.TENANT_ADMIN.value:
        raise BizException(ErrCode.FORBIDDEN, "租户管理员不可改角色，需由超管更换")
    role_id = await RbacDao.get_role_id(body.role)
    await RbacDao.assign_role(user_id, current.tenant_id, role_id)
    await AuditDao.write(
        tenant_id=current.tenant_id,
        user_id=current.user_id,
        action="rbac.grant",
        target=str(user_id),
        detail=f"角色={body.role}",
    )
    return success({"user_id": user_id, "role": body.role})


@router.delete("/{user_id}", summary="从本租户解绑用户")
async def delete_user(
    user_id: int,
    current: CurrentUser = Depends(get_current_user),  # noqa: B008
    __: object = Depends(require_scope(Scope.USER_DELETE)),  # noqa: B008
) -> Any:
    """从本租户解绑用户（不可解绑自己/管理员，写审计日志）。

    请求：path { user_id }
    权限：user:delete
    返回：{ user_id, removed }
    """
    if user_id == current.user_id:
        raise BizException(ErrCode.FORBIDDEN, "不能解绑自己")
    membership = await RbacDao.get_membership(user_id, current.tenant_id)
    if membership is None:
        raise BizException(ErrCode.NOT_FOUND, "该用户不在本租户")
    if membership == RoleName.TENANT_ADMIN.value:
        raise BizException(ErrCode.FORBIDDEN, "租户管理员不可删除，请先更换", http_status=409)
    removed = await RbacDao.delete_membership(user_id, current.tenant_id)
    await AuditDao.write(
        tenant_id=current.tenant_id,
        user_id=current.user_id,
        action="rbac.revoke",
        target=str(user_id),
        detail="从本租户解绑",
    )
    return success({"user_id": user_id, "removed": removed})


@router.get("/{user_id}", summary="本租户用户详情（与 admin/rbac/users/{id} 独立）")
async def get_user(
    user_id: int,
    current: CurrentUser = Depends(get_current_user),  # noqa: B008
    __: object = Depends(require_scope(Scope.USER_VIEW)),  # noqa: B008
) -> Any:
    """本租户用户详情（越租户直接 404，密码字段已剥离）。

    请求：path { user_id }
    权限：user:view
    返回：用户记录（无 password）
    """
    # 越租户窥探防护：不在本租户直接 404，不暴露存在性
    if await RbacDao.get_membership(user_id, current.tenant_id) is None:
        raise BizException(ErrCode.NOT_FOUND, "该用户不在本租户")
    row = await UserDao.get(user_id)
    if row is None:
        raise BizException(ErrCode.NOT_FOUND, f"用户不存在: {user_id}")
    # user 表含 password 列，响应一律剥掉，不外露
    item = {k: v for k, v in row.items() if k != "password"}
    return success(item)
