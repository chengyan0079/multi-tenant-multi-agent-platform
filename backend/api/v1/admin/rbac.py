"""超管 RBAC 端点（/api/v1/admin/**）。

- GET  /users                      全量用户只读（含租户/角色）—— 超管看全量；租户管理员仅本租户
- GET  /users/{id}                 用户详情 —— 超管看全量；租户管理员仅本租户
- GET  /roles                      角色目录与权限点 —— 超管 + 租户管理员（只读）
- PUT  /roles/{id}                  改角色名称/说明 —— 仅超管
- PUT  /roles/{id}/permissions     覆盖角色权限点（即时生效）—— 仅超管（全局角色，放开即跨租户提权）
- POST /roles                      新建角色 —— 仅超管
- DELETE /roles/{id}               删除角色（内置角色除外）—— 仅超管
- PUT  /rbac/users/{id}/role       改用户角色 —— 超管跨租户；租户管理员仅本租户且不能任命租户管理员

本模块鉴权不挂在装配整组 require_super_admin() 上（见 api/router.py）：角色目录需要
对超管 + 租户管理员开放，而其余写操作仅超管，因此每个端点自行声明依赖。
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, Query

from backend.api.v1.admin.schemas import RoleCreateIn, RolePermsIn, RoleUpdateIn, UserRoleIn
from backend.common.response import success
from backend.observability.exception import BizException, ErrCode
from backend.data.dao.ops.audit_dao import AuditDao
from backend.data.dao.auth.rbac_dao import RbacDao
from backend.data.dao.auth.tenant_dao import TenantDao
from backend.data.dao.auth.user_dao import UserDao
from backend.middleware.auth import CurrentUser, get_current_user
from backend.security.rbac import RoleName, Scope, VALID_SCOPES
from backend.security.security import (
    require_scope,
    require_super_admin,
)

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
    _a: object = Depends(require_super_admin()),  # noqa: B008
    _b: object = Depends(require_scope(Scope.USER_PAGE)),  # noqa: B008
    current: CurrentUser = Depends(get_current_user),  # noqa: B008
) -> Any:
    # 仅超管可入：tenant_id 参数指定过滤，不传看全量
    q_tenant = tenant_id if current.is_super_admin else current.home_tenant_id
    rows = await UserDao.list_users(
        tenant_id=q_tenant,
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


@router.get("/roles", summary="角色目录与权限点（分页）")
async def list_roles(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    _a: object = Depends(require_super_admin()),  # noqa: B008
    _b: object = Depends(require_scope(Scope.RBAC_PAGE)),  # noqa: B008
    current: CurrentUser = Depends(get_current_user),  # noqa: B008
) -> Any:
    rows = await RbacDao.list_roles_with_permissions()
    total = len(rows)
    start = (page - 1) * page_size
    paged = rows[start : start + page_size]
    return success({"items": paged, "total": total, "page": page, "page_size": page_size})


@router.get("/scopes", summary="全量权限点目录（与 Scope 同源）")
async def list_scopes(
    _u: object = Depends(get_current_user),  # noqa: B008
):
    """返回 `backend.security.rbac.Scope` 的全部权限点，供前端角色编辑下拉选择。

    以代码为单一权威来源：新增权限点只需在 Scope 中登记，前端自动全量展示。
    """
    return success({"items": sorted(VALID_SCOPES)})


@router.get("/users/{user_id}", summary="用户详情（仅超管）")
async def get_user(
    user_id: int,
    _a: object = Depends(require_super_admin()),  # noqa: B008
    _b: object = Depends(require_scope(Scope.USER_VIEW)),  # noqa: B008
    current: CurrentUser = Depends(get_current_user),  # noqa: B008
) -> Any:
    row = await UserDao.get(user_id)
    if row is None:
        raise BizException(ErrCode.NOT_FOUND, f"用户不存在: {user_id}")
    # 仅超管可入，可见任意租户用户
    if not current.is_super_admin and row.get("tenant_id") != current.home_tenant_id:
        raise BizException(ErrCode.FORBIDDEN, "只能查看本租户用户")
    # user 表含 password 列，响应一律剥掉，不外露
    item = {k: v for k, v in row.items() if k != "password"}
    return success(item)


@router.put("/roles/{role_id}/permissions", summary="覆盖角色权限点")
async def set_role_perms(
    role_id: int,
    body: RolePermsIn,
    _a: object = Depends(require_super_admin()),  # noqa: B008
    _b: object = Depends(require_scope(Scope.RBAC_UPDATE)),  # noqa: B008
    current: CurrentUser = Depends(get_current_user),  # noqa: B008
) -> Any:
    for s in body.scopes:
        if s not in VALID_SCOPES:
            raise BizException(ErrCode.PARAM_ERROR, f"非法权限点: {s}")
    roles = await RbacDao.list_roles_with_permissions()
    old = next((r["scopes"] for r in roles if r["role_id"] == role_id), [])
    await RbacDao.set_role_permissions(role_id, body.scopes)
    await AuditDao.write(
        action="rbac.role_permissions", target=str(role_id),
        detail=f"改前={old} 改后={body.scopes}", **_operator(current),
    )
    return success({"role_id": role_id, "scopes": body.scopes})


@router.put("/roles/{role_id}", summary="改角色名称/说明")
async def update_role(
    role_id: int,
    body: RoleUpdateIn,
    _a: object = Depends(require_super_admin()),  # noqa: B008
    _b: object = Depends(require_scope(Scope.RBAC_UPDATE)),  # noqa: B008
    current: CurrentUser = Depends(get_current_user),  # noqa: B008
) -> Any:
    # 权限点不在此接口改（走 /permissions），避免一次请求同时动身份与授权
    await RbacDao.update_role(
        role_id, body.name, body.description, user_id=current.user_id
    )
    await AuditDao.write(
        action="rbac.role_update", target=str(role_id),
        detail=f"name={body.name}", **_operator(current),
    )
    return success(
        {"role_id": role_id, "name": body.name, "description": body.description}
    )


@router.post("/roles", summary="新建角色（含权限点）")
async def create_role(
    body: RoleCreateIn,
    _a: object = Depends(require_super_admin()),  # noqa: B008
    _b: object = Depends(require_scope(Scope.RBAC_ADD)),  # noqa: B008
    current: CurrentUser = Depends(get_current_user),  # noqa: B008
) -> Any:
    for s in body.scopes:
        if s not in VALID_SCOPES:
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
    _a: object = Depends(require_super_admin()),  # noqa: B008
    _b: object = Depends(require_scope(Scope.RBAC_DELETE)),  # noqa: B008
    current: CurrentUser = Depends(get_current_user),  # noqa: B008
) -> Any:
    await RbacDao.delete_role(role_id)
    await AuditDao.write(
        action="rbac.role_delete", target=str(role_id),
        detail="删除角色", **_operator(current),
    )
    return success({"role_id": role_id})


@router.put("/rbac/users/{user_id}/role", summary="改用户角色（超管跨租户；租户管理员仅本租户，且不能任命租户管理员）")
async def change_user_role(
    user_id: int,
    body: UserRoleIn,
    _a: object = Depends(require_super_admin()),  # noqa: B008
    _b: object = Depends(require_scope(Scope.USER_UPDATE)),  # noqa: B008
    current: CurrentUser = Depends(get_current_user),  # noqa: B008
) -> Any:
    # 租户管理员：锁定本租户，且不可任命/更换租户管理员（租户管理归超管）
    if not current.is_super_admin:
        body.tenant_id = current.home_tenant_id
        if body.role == RoleName.TENANT_ADMIN.value:
            raise BizException(ErrCode.FORBIDDEN, "租户管理员不能任命租户管理员，仅超管可操作")
    if body.role == RoleName.ADMIN.value:
        raise BizException(ErrCode.PARAM_ERROR, "admin 角色不可通过此接口授予，仅种子预置")
    # 校验目标用户归属目标租户，防止越租户改角色
    target = await UserDao.get(user_id)
    if target is None:
        raise BizException(ErrCode.NOT_FOUND, f"用户不存在: {user_id}")
    if target.get("tenant_id") != body.tenant_id:
        raise BizException(ErrCode.FORBIDDEN, "只能修改本租户用户角色")
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
