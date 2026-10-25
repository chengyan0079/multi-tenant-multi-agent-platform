"""超管 RBAC 端点（/api/v1/admin/**）。

- GET  /users                      全量用户只读（含租户/角色）
- GET  /roles                      角色目录与权限点
- PUT  /roles/{id}/permissions     覆盖角色权限点（即时生效）
- PUT  /rbac/users/{id}/role       改任意租户用户的角色（student/teacher/tenant_admin，admin 不可经此授予）

鉴权由装配处统一挂 require_super_admin()，写操作叠加 require_scope 做接口级校验。
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, Query

from backend.api.v1.admin.schemas import RoleCreateIn, RolePermsIn, UserRoleIn
from backend.common.response import success
from backend.observability.exception import BizException, ErrCode
from backend.data.dao.ops.audit_dao import AuditDao
from backend.data.dao.auth.rbac_dao import RbacDao
from backend.data.dao.auth.tenant_dao import TenantDao
from backend.data.dao.auth.user_dao import UserDao
from backend.middleware.auth import CurrentUser, get_current_user
from backend.security.rbac import RoleName, Scope
from backend.security.security import require_scope

router = APIRouter(tags=["admin"])


def _operator(current: CurrentUser) -> dict[str, int]:
    return {"tenant_id": current.home_tenant_id, "user_id": current.user_id}


@router.get("/users", summary="全量用户（只读，分页）")
async def list_users(
    tenant_id: Optional[int] = Query(None),
    username: Optional[str] = Query(None),
    created_from: Optional[str] = Query(None, description="创建起始日期 YYYY-MM-DD"),
    created_to: Optional[str] = Query(None, description="创建截止日期 YYYY-MM-DD"),
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(20, ge=1, le=200, description="每页条数"),
    _: object = Depends(require_scope("user:read")),  # noqa: B008
    __: object = Depends(get_current_user),  # noqa: B008
) -> Any:
    rows = await UserDao.list_users(
        tenant_id=tenant_id,
        username=username,
        created_from=created_from,
        created_to=created_to,
    )
    # user 表含 password 列，响应一律剥掉，不外露
    items = [{k: v for k, v in r.items() if k != "password"} for r in rows]
    # 用户/租户属管理数据，规模可控，接口层分页切片；若后续用户量增大再下沉到 DAO 分页
    total = len(items)
    start = (page - 1) * page_size
    paged = items[start : start + page_size]
    return success({"items": paged, "total": total, "page": page, "page_size": page_size})


@router.get("/roles", summary="角色目录与权限点")
async def list_roles(
    _: object = Depends(require_scope("rbac:read")),  # noqa: B008
    __: object = Depends(get_current_user),  # noqa: B008
) -> Any:
    rows = await RbacDao.list_roles_with_permissions()
    return success({"items": rows, "total": len(rows)})


@router.put("/roles/{role_id}/permissions", summary="覆盖角色权限点")
async def set_role_perms(
    role_id: int,
    body: RolePermsIn,
    _: object = Depends(require_scope("rbac:write")),  # noqa: B008
    current: CurrentUser = Depends(get_current_user),  # noqa: B008
) -> Any:
    for s in body.scopes:
        try:
            Scope(s)
        except ValueError:
            raise BizException(ErrCode.PARAM_ERROR, f"非法权限点: {s}")
    roles = await RbacDao.list_roles_with_permissions()
    old = next((r["scopes"] for r in roles if r["role_id"] == role_id), [])
    await RbacDao.set_role_permissions(role_id, body.scopes)
    await AuditDao.write(
        action="rbac.role_permissions", target=str(role_id),
        detail=f"改前={old} 改后={body.scopes}", **_operator(current),
    )
    return success({"role_id": role_id, "scopes": body.scopes})


@router.post("/roles", summary="新建角色（含权限点）")
async def create_role(
    body: RoleCreateIn,
    _: object = Depends(require_scope("rbac:write")),  # noqa: B008
    current: CurrentUser = Depends(get_current_user),  # noqa: B008
) -> Any:
    for s in body.scopes:
        try:
            Scope(s)
        except ValueError:
            raise BizException(ErrCode.PARAM_ERROR, f"非法权限点: {s}")
    role_id = await RbacDao.create_role(
        body.name, body.description, body.scopes, user_id=current.user_id
    )
    await AuditDao.write(
        action="rbac.role_create", target=str(role_id),
        detail=f"name={body.name}", **_operator(current),
    )
    return success({"role_id": role_id, "name": body.name})


@router.delete("/roles/{role_id}", summary="删除角色（内置角色除外）")
async def delete_role(
    role_id: int,
    _: object = Depends(require_scope("rbac:write")),  # noqa: B008
    current: CurrentUser = Depends(get_current_user),  # noqa: B008
) -> Any:
    await RbacDao.delete_role(role_id)
    await AuditDao.write(
        action="rbac.role_delete", target=str(role_id),
        detail="删除角色", **_operator(current),
    )
    return success({"role_id": role_id})


@router.put("/rbac/users/{user_id}/role", summary="改任意租户用户角色")
async def change_user_role(
    user_id: int,
    body: UserRoleIn,
    _: object = Depends(require_scope("rbac:write")),  # noqa: B008
    current: CurrentUser = Depends(get_current_user),  # noqa: B008
) -> Any:
    if body.role == RoleName.ADMIN.value:
        raise BizException(ErrCode.PARAM_ERROR, "admin 角色不可通过此接口授予，仅种子预置")
    role_id = await RbacDao.get_role_id(body.role)
    if role_id is None:
        raise BizException(ErrCode.PARAM_ERROR, f"未知角色: {body.role}")
    if await TenantDao.get(body.tenant_id) is None:
        raise BizException(ErrCode.NOT_FOUND, f"租户不存在: {body.tenant_id}")
    if body.role == RoleName.TENANT_ADMIN.value:
        # 走原子更换（原管理员降 student），保持每租户恰 1 个管理员
        replaced = await RbacDao.set_tenant_admin(body.tenant_id, user_id)
    else:
        await RbacDao.assign_role(user_id, body.tenant_id, role_id)
        replaced = None
    await AuditDao.write(
        action="rbac.grant", target=f"{user_id}@{body.tenant_id}",
        detail=f"角色={body.role}", **_operator(current),
    )
    return success({"user_id": user_id, "tenant_id": body.tenant_id, "role": body.role, "replaced_user_id": replaced})
