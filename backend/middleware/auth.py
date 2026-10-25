"""
auth - 认证依赖 get_current_user（设计文档 §4）

token 单源（2026-10-24 定版）：身份只来自 Authorization: Bearer <JWT>，不读任何身份头、不读 body/query/cookie。
JWT payload：普通用户/租户管理员含 user_id + tenant_id；平台超管只含 user_id（tenant_id 不进 token）。
验签失败/过期 → 403；user_id 缺失或非整数 → 401；token 不含 tenant_id 且非超管 → 403。

解析流程（数据库为唯一真相源，无硬编码常量兜底）：
- 有 tenant_id → 租户分支：agent_user_tenant + agent_role + tenant 查身份（租户停用/无分配 → 403）；
- 无 tenant_id → 超管分支：主租户 + admin 角色判定，命中则 tenant_id=None、is_super_admin=True、scopes=种子里 admin 角色的具体权限点（无 "*"，菜单再由白名单收敛）。

写入 request.state：user_id / tenant_id（超管恒 None）/ home_tenant_id（user.tenant_id，仅审计归属）/
role_name / roles / is_super_admin / is_tenant_admin / scopes；并写入 contextvars（user_id_ctx / tenant_id_ctx）
供审计、memory、限流、数据过滤全链路消费（middleware 只写这一处）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from fastapi import Depends, HTTPException, Request
import jwt

from backend.app_state import app_state, tenant_id_ctx, user_id_ctx
from backend.data.dao.auth.user_dao import UserDao
from backend.security.rbac import Identity, RbacService
from backend.common.logger import get_logger

logger = get_logger("auth")


def _parse_int(v: object) -> int | None:
    """把 JWT 里的整数声明转成 int；空/None/非数字返回 None（允许 int 直接透传）。"""
    if v is None:
        return None
    if isinstance(v, int):
        return v
    s = str(v).strip()
    if s == "":
        return None
    try:
        return int(s)
    except (TypeError, ValueError):
        return None


@dataclass
class CurrentUser:
    """当前用户身份（贯穿全链路）。单租户内只任一角色，故角色为单值。"""

    user_id: int
    tenant_id: int | None
    home_tenant_id: int | None
    role_name: str
    is_super_admin: bool
    is_tenant_admin: bool
    scopes: list

    @property
    def roles(self) -> list:
        """兼容按角色列表判断的调用方（require_role 读的是 request.state.roles）。"""
        return [self.role_name]


def tenant_of(current: CurrentUser) -> int:
    """取已认证用户的租户 id。

    get_current_user 解析不到租户时已 403，这里只是把 Optional 收窄，并给绕过依赖
    直接构造 CurrentUser 的调用方一个明确的失败点（超管调业务接口）。
    """
    if current.tenant_id is None:
        raise HTTPException(status_code=403, detail="平台超管无租户上下文")
    return current.tenant_id


async def _resolve_tenant_identity(user_id: int, tenant_id: int) -> Identity:
    """租户分支：查库解析身份（分配不存在 / 租户停用 → 403）。"""
    try:
        identity = await RbacService.resolve_identity(user_id, tenant_id)
    except Exception as exc:
        # 数据库不可用时无法解析角色，按未授权处理（数据须提前录入）
        raise HTTPException(
            status_code=403, detail=f"角色解析失败（数据库不可用）：{exc}"
        )
    if identity is None:
        raise HTTPException(
            status_code=403,
            detail=f"用户 {user_id} 不属于租户 {tenant_id} 或租户已停用",
        )
    return identity


async def _resolve_super_admin(user_id: int) -> Identity:
    """超管分支：仅按 user_id + 主租户 + admin 角色判定；非超管 → 403。"""
    try:
        identity = await RbacService.resolve_super_admin(user_id)
    except Exception as exc:
        raise HTTPException(
            status_code=403, detail=f"角色解析失败（数据库不可用）：{exc}"
        )
    if identity is None:
        raise HTTPException(
            status_code=403, detail="token 不含租户，且该用户不是平台超管"
        )
    return identity


async def get_current_user(request: Request) -> CurrentUser:
    """FastAPI 依赖：token 单源解析身份并查库授权；无登录。"""
    cfg = app_state.settings.security
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="缺少 Authorization")
    if not cfg.jwt_secret:
        raise HTTPException(status_code=401, detail="JWT_SECRET 未配置")
    try:
        payload = jwt.decode(
            header[len("Bearer "):], cfg.jwt_secret, algorithms=[cfg.jwt_algorithm]
        )
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=403, detail="凭证无效或过期")

    user_id = _parse_int(payload.get("user_id"))
    if user_id is None:
        raise HTTPException(status_code=401, detail="user_id 必须为整数")

    tenant_id_raw = payload.get("tenant_id")
    tenant_id = _parse_int(tenant_id_raw) if tenant_id_raw is not None else None

    # 数据库为唯一真相源：有 tenant_id 走租户分支，否则走超管分支
    if tenant_id is not None:
        identity = await _resolve_tenant_identity(user_id, tenant_id)
    else:
        identity = await _resolve_super_admin(user_id)

    # home_tenant_id 取 user.tenant_id（审计归属，超管也用主租户），仅用于审计列，不参与数据过滤
    user = await UserDao.get(user_id)
    if user is None:
        raise HTTPException(status_code=403, detail="用户不存在或已被删除")
    home_tenant_id = user.get("tenant_id")

    # 写入 request.state 与 contextvars，下游 require_role/require_scope、memory、audit 消费
    request.state.user_id = user_id
    request.state.tenant_id = identity.tenant_id
    request.state.home_tenant_id = home_tenant_id
    request.state.role_name = identity.role_name
    request.state.roles = [identity.role_name]
    request.state.is_super_admin = identity.is_super_admin
    request.state.is_tenant_admin = identity.is_tenant_admin
    request.state.scopes = identity.scopes
    user_id_ctx.set(user_id)
    tenant_id_ctx.set(identity.tenant_id)
    return CurrentUser(
        user_id=user_id,
        tenant_id=identity.tenant_id,
        home_tenant_id=home_tenant_id,
        role_name=identity.role_name,
        is_super_admin=identity.is_super_admin,
        is_tenant_admin=identity.is_tenant_admin,
        scopes=identity.scopes,
    )
