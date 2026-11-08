"""超管 RBAC 端点（/api/v1/admin/**）。

角色目录对超管 + 租户管理员开放，其余写操作仅超管，故整组不挂统一鉴权，由端点各自声明。
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
    _b: object = Depends(require_scope(Scope.USER_PAGE)),  # noqa: B008
    current: CurrentUser = Depends(get_current_user),  # noqa: B008
) -> Any:
    # /admin 为全局视角，tenant_id 指定租户过滤，不传看全平台
    rows, total = await UserDao.list_users(
        tenant_id=tenant_id,
        username=username,
        created_from=created_from,
        created_to=created_to,
        page=page,
        page_size=page_size,
    )
    # user 表含 password 列，响应一律剥掉
    items = [{k: v for k, v in r.items() if k != "password"} for r in rows]
    return success({"items": items, "total": total, "page": page, "page_size": page_size})


@router.get("/roles", summary="角色目录与权限点（分页）")
async def list_roles(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    _b: object = Depends(require_scope(Scope.ROLE_PAGE)),  # noqa: B008
    current: CurrentUser = Depends(get_current_user),  # noqa: B008
) -> Any:
    rows, total = await RbacDao.list_roles_paged(page=page, page_size=page_size)
    return success({"items": rows, "total": total, "page": page, "page_size": page_size})


@router.get("/scopes", summary="全量权限点目录（按 Scope 派生，供角色编辑多选）")
async def list_scopes(
    _: object = Depends(require_scope(Scope.ROLE_PAGE)),  # noqa: B008
    __: object = Depends(get_current_user),  # noqa: B008
):
    # 单一权威来源是 security.rbac.Scope（VALID_SCOPES 由其派生）：
    # 分组与清单都直接由 scope 字符串拆出资源得到，接口层不硬编码任何中文。
    # 前端只用 items（扁平 scope 列表）自行分组展示。
    grouped: dict[str, list[str]] = {}
    for scope in VALID_SCOPES:
        if ":" not in scope:
            continue
        res = scope.split(":", 1)[0]
        grouped.setdefault(res, []).append(scope)
    return success({
        "groups": [
            {"resource": res, "scopes": sorted(scopes)}
            for res, scopes in sorted(grouped.items())
        ],
        "items": sorted(VALID_SCOPES),
    })


@router.get("/users/{user_id}", summary="用户详情（仅超管）")
async def get_user(
    user_id: int,

    _b: object = Depends(require_scope(Scope.USER_VIEW)),  # noqa: B008
    current: CurrentUser = Depends(get_current_user),  # noqa: B008
) -> Any:
    row = await UserDao.get(user_id)
    if row is None:
        raise BizException(ErrCode.NOT_FOUND, f"用户不存在: {user_id}")
    # /admin 路由为全局视角（权限由 scope 决定），可见任意租户用户
    # user 表含 password 列，响应一律剥掉，不外露
    item = {k: v for k, v in row.items() if k != "password"}
    return success(item)


@router.put("/roles/{role_id}/permissions", summary="覆盖角色权限点")
async def set_role_perms(
    role_id: int,
    body: RolePermsIn,

    _b: object = Depends(require_scope(Scope.ROLE_UPDATE)),  # noqa: B008
    current: CurrentUser = Depends(get_current_user),  # noqa: B008
) -> Any:
    for s in body.scopes:
        if s not in VALID_SCOPES:
            raise BizException(ErrCode.PARAM_ERROR, f"非法权限点: {s}")
    roles = await RbacDao.list_roles_with_permissions()
    role = next((r for r in roles if r["role_id"] == role_id), None)
    if role is None:
        raise BizException(ErrCode.NOT_FOUND, f"角色不存在: {role_id}")
    # admin 为内置超管锚点，权限点由种子固化，禁止前端覆盖（避免误清空导致超管失权）
    if role["name"] == RoleName.ADMIN.value:
        raise BizException(ErrCode.PARAM_ERROR, "内置角色 admin 权限不可修改")
    old = role["scopes"]
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

    _b: object = Depends(require_scope(Scope.ROLE_UPDATE)),  # noqa: B008
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

    _b: object = Depends(require_scope(Scope.ROLE_ADD)),  # noqa: B008
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

    _b: object = Depends(require_scope(Scope.ROLE_DELETE)),  # noqa: B008
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

    _b: object = Depends(require_scope(Scope.USER_UPDATE)),  # noqa: B008
    current: CurrentUser = Depends(get_current_user),  # noqa: B008
) -> Any:
    # /admin 路由为全局视角（权限由 scope 决定），不按角色锁租户；
    # admin 角色仍不可通过此接口授予（见下方校验）。
    if body.role == RoleName.ADMIN.value:
        raise BizException(ErrCode.PARAM_ERROR, "admin 角色不可通过此接口授予，仅种子预置")
    # 校验目标用户归属目标租户，防止越租户改角色
    target = await UserDao.get(user_id)
    if target is None:
        raise BizException(ErrCode.NOT_FOUND, f"用户不存在: {user_id}")
    if target.get("is_super_admin"):
        raise BizException(ErrCode.FORBIDDEN, "超管账号不可修改角色")
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
    return success({
        "user_id": user_id,
        "tenant_id": body.tenant_id,
        "role": body.role,
        "replaced_user_id": replaced,
    })
