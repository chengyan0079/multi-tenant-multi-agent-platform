"""认证依赖 get_current_user：token 单源解析身份并查库授权。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from fastapi import Depends, HTTPException, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import jwt

from backend.app_state import app_state, tenant_id_ctx, user_id_ctx
from backend.data.dao.auth.user_dao import UserDao
from backend.security.rbac import Identity, RbacService
from backend.common.logger import get_logger
from backend.common.redis_session import touch_session

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

    user_id: int  # 用户 id
    tenant_id: int | None  # 当前租户 id；超管为 None
    home_tenant_id: int | None  # 归属租户（仅审计用，不参与数据过滤）；超管为 None
    role_name: str  # 角色名（单租户内单值）
    is_super_admin: bool  # 是否平台超管
    is_tenant_admin: bool  # 是否租户管理员
    scopes: list  # 权限点集合

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
        raise HTTPException(status_code=403, detail=f"角色解析失败（数据库不可用）：{exc}")
    if identity is None:
        raise HTTPException(
            status_code=403,
            detail=f"用户 {user_id} 不属于租户 {tenant_id} 或租户已停用",
        )
    return identity


async def _resolve_super_admin(user_id: int) -> Identity:
    """超管分支：仅按 agent_user.is_super_admin 判定；非超管 → 403。"""
    try:
        identity = await RbacService.resolve_super_admin(user_id)
    except Exception as exc:
        raise HTTPException(status_code=403, detail=f"角色解析失败（数据库不可用）：{exc}")
    if identity is None:
        raise HTTPException(status_code=403, detail="token 不含租户，且该用户不是平台超管")
    return identity


# 仅用于把 HTTPBearer 登记进 OpenAPI（让 Swagger UI 出现 Authorize 按钮）；
# auto_error=False：缺/错 token 时不自动抛错，交给我们自己的提示口径。
_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Security(_bearer),
) -> CurrentUser:
    """FastAPI 依赖：token 单源解析身份并查库授权；无登录。"""
    cfg = app_state.settings.security
    # 优先用 Security 注入的凭证（Swagger UI / OpenAPI 场景）；
    # 直接调用（如单测未走 FastAPI 依赖注入）时回落到手动读 header，保持原行为。
    if isinstance(credentials, HTTPAuthorizationCredentials):
        token = credentials.credentials
    else:
        auth = request.headers.get("Authorization", "")
        token = auth[len("Bearer ") :] if auth.startswith("Bearer ") else None
    if not token:
        raise HTTPException(status_code=401, detail="缺少 Authorization")
    if not cfg.jwt_secret:
        raise HTTPException(status_code=401, detail="JWT_SECRET 未配置")
    try:
        payload = jwt.decode(token, cfg.jwt_secret, algorithms=[cfg.jwt_algorithm])
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=403, detail="凭证无效或过期")

    user_id = _parse_int(payload.get("user_id"))
    if user_id is None:
        raise HTTPException(status_code=401, detail="user_id 必须为整数")

    tenant_id_raw = payload.get("tenant_id")
    tenant_id = _parse_int(tenant_id_raw) if tenant_id_raw is not None else None

    # 登录会话层（Redis 滑动续期）：jti 缺失的旧 token 跳过，兼容功能上线前的 token
    jti = payload.get("jti")
    if jti:
        if not await touch_session(jti):
            raise HTTPException(status_code=401, detail="登录已失效，请重新登录")
    request.state.jti = jti

    # 数据库为唯一真相源：有 tenant_id 走租户分支，否则走超管分支
    if tenant_id is not None:
        identity = await _resolve_tenant_identity(user_id, tenant_id)
    else:
        identity = await _resolve_super_admin(user_id)

    # home_tenant_id 取 user.tenant_id（审计归属），仅用于审计列，不参与数据过滤；超管为 None
    user = await UserDao.get(user_id)
    if user is None:
        raise HTTPException(status_code=403, detail="用户不存在或已被删除")
    if not user.get("enabled"):
        raise HTTPException(status_code=403, detail="账号已禁用")
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
