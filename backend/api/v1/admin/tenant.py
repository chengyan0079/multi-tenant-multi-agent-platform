"""超管租户管理端点（/api/v1/admin/tenants）。

鉴权由装配处统一挂 require_super_admin()，写操作再叠加 require_scope(tenant:*) 做接口级校验。
管理员更换走 PUT /{id}/manager：原子地把原管理员降为 student 再写入新 tenant_admin（§6.2）。
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, Query

from backend.api.v1.admin.schemas import TenantIn, TenantManagerIn, TenantUpdate
from backend.common.response import success
from backend.observability.exception import BizException, ErrCode
from backend.data.dao.ops.audit_dao import AuditDao
from backend.data.dao.auth.rbac_dao import RbacDao
from backend.data.dao.auth.tenant_dao import TenantDao
from backend.data.dao.auth.user_dao import UserDao
from backend.middleware.auth import CurrentUser, get_current_user
from backend.security.security import require_scope

router = APIRouter(prefix="/tenants", tags=["admin"])


def _operator(current: CurrentUser) -> dict[str, int]:
    """审计写入参数：tenant_id 取操作者归属租户（超管用主租户），user_id 取当前用户。"""
    return {"tenant_id": current.home_tenant_id, "user_id": current.user_id}


@router.get("", summary="租户列表（含管理员与用户数，分页）")
async def list_tenants(
    name: Optional[str] = Query(None, description="按租户名模糊匹配"),
    created_from: Optional[str] = Query(None, description="创建起始日期 YYYY-MM-DD"),
    created_to: Optional[str] = Query(None, description="创建截止日期 YYYY-MM-DD"),
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(20, ge=1, le=200, description="每页条数"),
    _: object = Depends(require_scope("tenant:read")),  # noqa: B008
    __: object = Depends(get_current_user),  # noqa: B008
) -> Any:
    rows = await TenantDao.list_with_stats(created_from=created_from, created_to=created_to)
    if name:
        rows = [r for r in rows if name in (r.get("name") or "")]
    # 租户数量小，接口层过滤 + 分页切片；保持与用户列表一致的处理方式
    total = len(rows)
    start = (page - 1) * page_size
    paged = rows[start : start + page_size]
    return success({"items": paged, "total": total, "page": page, "page_size": page_size})


@router.post("", summary="新建租户")
async def create_tenant(
    body: TenantIn,
    _: object = Depends(require_scope("tenant:write")),  # noqa: B008
    current: CurrentUser = Depends(get_current_user),  # noqa: B008
) -> Any:
    new_id = await TenantDao.create(body.name)
    await AuditDao.write(
        action="tenant.create", target=str(new_id), detail=f"新建租户 {body.name}",
        **_operator(current),
    )
    return success({"id": new_id})


@router.put("/{tenant_id}", summary="改名 / 启停")
async def update_tenant(
    tenant_id: int,
    body: TenantUpdate,
    _: object = Depends(require_scope("tenant:write")),  # noqa: B008
    current: CurrentUser = Depends(get_current_user),  # noqa: B008
) -> Any:
    tenant = await TenantDao.get(tenant_id)
    if tenant is None:
        raise BizException(ErrCode.NOT_FOUND, f"租户不存在: {tenant_id}")
    if body.enabled is False and tenant["is_primary"]:
        raise BizException(ErrCode.PARAM_ERROR, "主租户不允许停用")
    await TenantDao.update(tenant_id, name=body.name, enabled=body.enabled)
    await AuditDao.write(
        action="tenant.update", target=str(tenant_id),
        detail=f"name={body.name}, enabled={body.enabled}", **_operator(current),
    )
    return success({"id": tenant_id})


@router.put("/{tenant_id}/manager", summary="指定/更换租户管理员")
async def set_manager(
    tenant_id: int,
    body: TenantManagerIn,
    _: object = Depends(require_scope("tenant:write")),  # noqa: B008
    current: CurrentUser = Depends(get_current_user),  # noqa: B008
) -> Any:
    tenant = await TenantDao.get(tenant_id)
    if tenant is None:
        raise BizException(ErrCode.NOT_FOUND, f"租户不存在: {tenant_id}")

    user = await UserDao.get_by_username(body.username)
    if user is None:
        if not body.password:
            raise BizException(ErrCode.PARAM_ERROR, "新管理员需提供 password")
        user_id = await UserDao.create(
            username=body.username,
            name=body.name or body.username,
            password=body.password,
            tenant_id=tenant_id,
        )
    else:
        user_id = user["id"]

    replaced = await RbacDao.set_tenant_admin(tenant_id, user_id)
    detail = f"设置管理员 user={user_id}" + (
        f"，替换原管理员 user={replaced}" if replaced else ""
    )
    await AuditDao.write(
        action="tenant.manager", target=str(tenant_id), detail=detail, **_operator(current)
    )
    return success({"tenant_id": tenant_id, "user_id": user_id, "replaced_user_id": replaced})
