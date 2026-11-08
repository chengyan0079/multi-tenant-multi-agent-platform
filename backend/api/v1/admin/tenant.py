"""超管租户管理端点（/api/v1/admin/tenants）。"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, Query

from backend.api.v1.admin.schemas import EnabledIn, TenantIn, TenantManagerIn
from backend.common.response import success
from backend.observability.exception import BizException, ErrCode
from backend.data.dao.ops.audit_dao import AuditDao
from backend.data.dao.auth.rbac_dao import RbacDao
from backend.data.dao.auth.tenant_dao import TenantDao
from backend.data.dao.auth.user_dao import UserDao
from backend.common.redis_session import delete_sessions_by_tenant
from backend.middleware.auth import CurrentUser, get_current_user
from backend.security.rbac import Scope, RoleName
from backend.security.security import require_scope
from backend.data.sql import session_scope, fetch_value, execute_write
from sqlalchemy import text

router = APIRouter(prefix="/tenants", tags=["admin"])

# 平台超管租户：建库固化，id 恒为 0，仅作超管上传文件等场景的归属租户，禁止任何删改
SUPER_ADMIN_TENANT_ID = 0

# 一步建租户+主用户+授权 tenant_admin 的原子 SQL（共享同一 session 事务）
_INSERT_TENANT = text("INSERT INTO agent_tenant (name, enabled) VALUES (:name, true) RETURNING id")
_INSERT_USER = text(
    'INSERT INTO "agent_user" (username, name, password, tenant_id) '
    "VALUES (:username, :name, :password, :tenant_id) RETURNING id"
)
# created_at 在 DDL 里没有 DEFAULT，必须显式给值（否则 NOT NULL 约束报错）
_INSERT_MEMBERSHIP = text(
    "INSERT INTO agent_user_tenant (user_id, tenant_id, role_id, created_at) "
    "VALUES (:user_id, :tenant_id, :role_id, now()) "
    "ON CONFLICT (user_id, tenant_id) DO UPDATE SET role_id = EXCLUDED.role_id"
)


def _operator(current: CurrentUser) -> dict[str, int | None]:
    """审计写入参数：tenant_id 取操作者归属租户（超管为 NULL），user_id 取当前用户。"""
    return {"tenant_id": current.home_tenant_id, "user_id": current.user_id}


@router.get("", summary="租户列表（含管理员与用户数，分页）")
async def list_tenants(
    name: Optional[str] = Query(None, description="按租户名模糊匹配"),
    created_from: Optional[str] = Query(None, description="创建起始日期 YYYY-MM-DD"),
    created_to: Optional[str] = Query(None, description="创建截止日期 YYYY-MM-DD"),
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(20, ge=1, le=200, description="每页条数"),
    _: object = Depends(require_scope(Scope.TENANT_PAGE)),  # noqa: B008
    __: object = Depends(get_current_user),  # noqa: B008
) -> Any:
    rows, total = await TenantDao.list_with_stats(
        name=name,
        created_from=created_from,
        created_to=created_to,
        page=page,
        page_size=page_size,
    )
    return success({"items": rows, "total": total, "page": page, "page_size": page_size})


@router.get("/{tenant_id}", summary="租户详情")
async def get_tenant(
    tenant_id: int,
    _: object = Depends(require_scope(Scope.TENANT_VIEW)),  # noqa: B008
    __: object = Depends(get_current_user),  # noqa: B008
) -> Any:
    row = await TenantDao.get_with_stats(tenant_id)
    if row is None:
        raise BizException(ErrCode.NOT_FOUND, f"租户不存在: {tenant_id}")
    return success(row)


@router.post("", summary="新建租户并创建主租户用户（仅超管，原子操作）")
async def create_tenant(
    body: TenantIn,
    _: object = Depends(require_scope(Scope.TENANT_ADD)),  # noqa: B008
    current: CurrentUser = Depends(get_current_user),  # noqa: B008
) -> Any:
    if await TenantDao.get_by_name(body.name) is not None:
        raise BizException(ErrCode.PARAM_ERROR, f"租户名称已存在: {body.name}")

    mgr = body.manager
    if not mgr.username or not mgr.password:
        raise BizException(ErrCode.PARAM_ERROR, "主租户用户需提供用户名与密码")
    if await UserDao.get_by_username(mgr.username) is not None:
        raise BizException(ErrCode.PARAM_ERROR, f"登录名已存在: {mgr.username}")

    role_id = await RbacDao.get_role_id(RoleName.TENANT_ADMIN.value)
    if role_id is None:
        raise BizException(
            ErrCode.PARAM_ERROR,
            "tenant_admin 角色不存在，请先在『权限中心』创建该角色",
        )

    # 原子事务：建租户 → 建主用户 → 绑定 tenant_admin
    async with session_scope() as session:
        tenant_id = int(await fetch_value(session, _INSERT_TENANT, {"name": body.name}))
        user_id = int(await fetch_value(
            session,
            _INSERT_USER,
            {
                "username": mgr.username,
                "name": mgr.name or mgr.username,
                "password": mgr.password,
                "tenant_id": tenant_id,
            },
        ))
        await execute_write(
            session,
            _INSERT_MEMBERSHIP,
            {"user_id": user_id, "tenant_id": tenant_id, "role_id": role_id},
        )

    await AuditDao.write(
        action="tenant.create",
        target=str(tenant_id),
        detail=f"新建租户 {body.name} + 主用户 {mgr.username}",
        **_operator(current),
    )
    return success({"tenant_id": tenant_id, "user_id": user_id})


@router.patch("/{tenant_id}/status", summary="状态变更（启停）")
async def set_status(
    tenant_id: int,
    body: EnabledIn,
    _: object = Depends(require_scope(Scope.TENANT_STATUS)),  # noqa: B008
    current: CurrentUser = Depends(get_current_user),  # noqa: B008
) -> Any:
    if tenant_id == SUPER_ADMIN_TENANT_ID:
        raise BizException(ErrCode.PARAM_ERROR, "平台超管租户(id=0)禁止启停")
    tenant = await TenantDao.get(tenant_id)
    if tenant is None:
        raise BizException(ErrCode.NOT_FOUND, f"租户不存在: {tenant_id}")
    old_enabled = tenant["enabled"]
    await TenantDao.update(tenant_id, enabled=body.enabled)

    detail = f"enabled={body.enabled}"
    # 停用租户：级联禁用其下所有用户并强制下线
    if old_enabled and not body.enabled:
        disabled = await TenantDao.set_users_enabled(tenant_id, False)
        kicked = await delete_sessions_by_tenant(tenant_id)
        detail = f"已停用，级联禁用用户 {disabled} 个并强踢会话 {kicked} 个"

    await AuditDao.write(
        action="tenant.status", target=str(tenant_id),
        detail=detail, **_operator(current),
    )
    return success({"id": tenant_id, "enabled": body.enabled})


@router.delete("/{tenant_id}", summary="删除租户（仅超管，级联清理本租户成员与用户）")
async def delete_tenant(
    tenant_id: int,
    _: object = Depends(require_scope(Scope.TENANT_DELETE)),  # noqa: B008
    current: CurrentUser = Depends(get_current_user),  # noqa: B008
) -> Any:
    if tenant_id == SUPER_ADMIN_TENANT_ID:
        raise BizException(ErrCode.PARAM_ERROR, "平台超管租户(id=0)禁止删除")
    tenant = await TenantDao.get(tenant_id)
    if tenant is None:
        raise BizException(ErrCode.NOT_FOUND, f"租户不存在: {tenant_id}")
    # 先清会话（随后用户将被删，value.tenant_id 匹配需在删用户前完成），再级联删成员/用户/租户
    kicked = await delete_sessions_by_tenant(tenant_id)
    stats = await TenantDao.delete(tenant_id)
    await AuditDao.write(
        action="tenant.delete",
        target=str(tenant_id),
        detail=(
            f"删除租户 {tenant['name']}，清理成员关系 "
            f"{stats['deleted_memberships']} 条、用户 {stats['deleted_users']} 个，强踢会话 {kicked} 个"
        ),
        **_operator(current),
    )
    return success({"id": tenant_id, **stats, "kicked": kicked})
