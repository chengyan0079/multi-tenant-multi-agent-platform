"""认证接口：登录签发 token、当前用户菜单树、当前身份、登出。"""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Depends, Request

from backend.api.v1.auth.schemas import LoginIn
from backend.app_state import app_state, trace_id_ctx
from backend.common.logger import get_logger
from backend.common.response import success
from backend.data.dao.auth.login_log_dao import LoginLogDao
from backend.data.dao.auth.menu_dao import MenuDao
from backend.data.dao.auth.rbac_dao import RbacDao
from backend.data.dao.auth.user_dao import UserDao
from backend.middleware.auth import CurrentUser, get_current_user
import secrets

from backend.common.redis_session import create_session, delete_session
from backend.observability.exception import AuthError, ErrCode
from backend.security.jwt import create_access_token
from backend.security.rbac import RbacService

logger = get_logger("auth")

router = APIRouter(tags=["auth"])

# 只需区分「浏览器 / 系统」几类，不引 UA 解析库；顺序有讲究：Edge/Opera 的 UA 里也含 Chrome
_BROWSER_RULES: tuple[tuple[str, str], ...] = (
    (r"Edg/", "Edge"),
    (r"OPR/", "Opera"),
    (r"Chrome/", "Chrome"),
    (r"Firefox/", "Firefox"),
    (r"Safari/", "Safari"),
    (r"curl/", "curl"),
    (r"python-requests/|httpx/|aiohttp/", "脚本"),
)
_OS_RULES: tuple[tuple[str, str], ...] = (
    (r"Windows NT", "Windows"),
    (r"Android", "Android"),
    (r"iPhone|iPad|iPod", "iOS"),
    (r"Mac OS X", "macOS"),
    (r"Linux", "Linux"),
)


def _parse_client(ua: str) -> str:
    """从 UA 粗提「浏览器 / 系统」，识别不出就当空串。"""
    browser = next((n for p, n in _BROWSER_RULES if re.search(p, ua)), "")
    system = next((n for p, n in _OS_RULES if re.search(p, ua)), "")
    return " / ".join(x for x in (browser, system) if x)


def _client_meta(request: Request) -> tuple[str, str, str]:
    """取 (ip, UA 原文, 解析后的客户端)。

    反向代理下直接取 request.client 会拿到代理地址，故 X-Forwarded-For 首段优先。
    """
    xff = request.headers.get("x-forwarded-for", "")
    ip = xff.split(",")[0].strip() if xff else (request.client.host if request.client else "")
    ua = request.headers.get("user-agent", "")
    return ip[:64], ua[:512], _parse_client(ua)


async def _record_login(
    request: Request,
    *,
    username: str,
    success: bool,
    user_id: int | None = None,
    tenant_id: int | None = None,
    fail_reason: str | None = None,
) -> None:
    """写登录日志。旁路操作：写失败只告警，绝不改变登录结果。"""
    ip, ua, client = _client_meta(request)
    try:
        await LoginLogDao.write(
            success=success,
            username=username[:64],
            user_id=user_id,
            tenant_id=tenant_id,
            fail_reason=fail_reason[:128] if fail_reason else None,
            ip=ip,
            user_agent=ua,
            client=client,
            trace_id=trace_id_ctx.get(),
        )
    except Exception:  # noqa: BLE001  旁路
        logger.exception("登录日志写入失败（不影响登录结果）")


async def _login(username: str, password: str, tenant_id: int | None = None) -> dict[str, Any]:
    """登录核心：校验凭证 → 判定超管/租户用户 → 选租户 → 签发 JWT → 组装菜单。

    超管（agent_user.is_super_admin 标记）不含租户，token 只放 user_id，current_tenant=null。
    """
    user = await RbacService.authenticate(username, password)
    if user is None:
        raise AuthError("用户名或密码错误")
    user_id = user["id"]
    cfg = app_state.settings.security

    # 超管分支：只认 agent_user.is_super_admin 标记
    sa = await RbacDao.get_super_admin_identity(user_id)
    if sa is not None:
        scopes = sa["scopes"]  # 种子里 admin 角色的具体权限点（不含通配）
        jti = secrets.token_hex(16)
        token = create_access_token(user_id, jti=jti)
        await create_session(jti, user_id, None)
        menus = await MenuDao.build(scopes)
        return {
            "token": token,
            "expires_in": cfg.jwt_expire_minutes * 60,
            "user": {"user_id": user_id, "username": user["username"], "name": user["name"]},
            "is_super_admin": True,
            "is_tenant_admin": False,
            "current_tenant": None,
            "scopes": scopes,
            "menus": menus,
        }

    # 租户用户分支：先取全部分配，挑一个启用的租户
    assignments = await RbacDao.get_user_assignments(user_id)
    enabled = [a for a in assignments if a["tenant_enabled"]]
    if not enabled:
        raise AuthError("该用户未分配任何启用的租户", code=ErrCode.FORBIDDEN, http_status=403)
    if tenant_id is not None:
        chosen = next((a for a in enabled if a["tenant_id"] == tenant_id), None)
        if chosen is None:
            raise AuthError(
                "指定的租户不在该用户的可用租户内", code=ErrCode.FORBIDDEN, http_status=403
            )
    else:
        home = user.get("tenant_id")
        chosen = next((a for a in enabled if a["tenant_id"] == home), None) or enabled[0]

    identity = await RbacService.resolve_identity(user_id, chosen["tenant_id"])
    if identity is None:
        raise AuthError("角色解析失败", code=ErrCode.FORBIDDEN, http_status=403)
    jti = secrets.token_hex(16)
    token = create_access_token(user_id, tenant_id=chosen["tenant_id"], jti=jti)
    await create_session(jti, user_id, chosen["tenant_id"])
    menus = await MenuDao.build(identity.scopes)
    return {
        "token": token,
        "expires_in": cfg.jwt_expire_minutes * 60,
        "user": {"user_id": user_id, "username": user["username"], "name": user["name"]},
        "is_super_admin": False,
        "is_tenant_admin": identity.is_tenant_admin,
        "current_tenant": {
            "id": chosen["tenant_id"],
            "name": chosen["tenant_name"],
        },
        "scopes": identity.scopes,
        "menus": menus,
    }


@router.post("/login", summary="登录")
async def login(request: Request, body: LoginIn) -> Any:
    """登录并签发 token。每次尝试都落一行登录日志，成功与失败都记。"""
    try:
        result = await _login(body.username, body.password, body.tenant_id)
    except AuthError as exc:
        # 失败也记：撞库与误配置（如用户未分配租户）都靠这条线索
        await _record_login(request, username=body.username, success=False, fail_reason=exc.msg)
        raise
    await _record_login(
        request,
        username=body.username,
        success=True,
        user_id=result["user"]["user_id"],
        tenant_id=(result["current_tenant"] or {}).get("id"),
    )
    return success(result)


@router.get("/menus", summary="当前用户菜单树")
async def menus(current: CurrentUser = Depends(get_current_user)) -> Any:
    """按当前用户 scopes 下发菜单树（超管仅基建菜单）。

    请求：无
    权限：登录态
    返回：{ menus: [...] }
    """
    tree = await MenuDao.build(current.scopes)
    return success({"menus": tree})


@router.get("/me", summary="当前身份")
async def me(current: CurrentUser = Depends(get_current_user)) -> Any:
    """返回当前用户身份与权限信息。

    请求：无
    权限：登录态
    返回：{ user_id, username, name, tenant_id, is_super_admin, is_tenant_admin, role_name, scopes }
    """
    user = await UserDao.get(current.user_id)
    return success(
        {
            "user_id": current.user_id,
            "username": user["username"] if user else None,
            "name": user["name"] if user else None,
            "tenant_id": current.tenant_id,
            "home_tenant_id": current.home_tenant_id,
            "is_super_admin": current.is_super_admin,
            "is_tenant_admin": current.is_tenant_admin,
            "role_name": current.role_name,
            "scopes": current.scopes,
        }
    )


@router.post("/logout", summary="登出（使当前 token 立即失效）")
async def logout(request: Request, current: CurrentUser = Depends(get_current_user)) -> Any:
    """删 Redis 会话 key，当前 token 立即失效；多端各自独立，只清这一端。"""
    jti = getattr(request.state, "jti", None)
    if jti:
        await delete_session(jti)
    return success({"logged_out": True})
