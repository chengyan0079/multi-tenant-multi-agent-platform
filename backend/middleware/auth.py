"""
auth - 认证依赖 get_current_user（设计文档 §9.1 ①；本项目不做登录）

后端不做登录：身份由上游网关/SSO 断言后注入，后端只「验签 + 查库授权」：
1) 网关 JWT 模式：Authorization: Bearer <JWT>，后端仅 jwt.decode 验签名（payload 只含 user_id），
   不验密码；角色/租户全部查库，角色变更即时生效。
2) 信任头模式（内网/开发）：trust_headers=True 时直接信 X-User-Id / X-Tenant-Id（建议加 HMAC 防伪造）。
3) 开发身份默认：dev_user_id/dev_tenant_id 非空且无任何身份时，作为「你是谁」的默认值
   （仍须库中存在对应 agent_user_tenant 分配，否则按未授权处理）。

角色/权限唯一真相源是数据库（agent_role / agent_role_permission / agent_user_tenant），
数据须提前录入（ensure_default_roles() 或 scripts/seed_rbac.sql）。后端不再用硬编码常量兜底：
解析不到分配即视为未授权（403）。无论哪种模式，最终都查表得到
(tenant_id, roles[], scopes[])，写入 request.state 并贯穿全链路（含 contextvars）。
"""
from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from typing import Optional

from fastapi import Depends, HTTPException, Request
from jose import JWTError, jwt

from backend.app_state import app_state, tenant_id_ctx
from backend.core.rbac import RbacService
from backend.common.logger import get_logger

logger = get_logger("auth")


@dataclass
class CurrentUser:
    """当前用户身份（贯穿全链路）。单租户内只任一角色，故 roles 为单元素列表。"""

    user_id: str
    tenant_id: str
    roles: list
    scopes: list


# 当前操作人（请求作用域内），审批流/审计等取操作人时使用
user_id_ctx: ContextVar[str | None] = ContextVar("user_id", default=None)


async def _resolve_identity(user_id: str, tenant_id: str) -> tuple[str, list[str]]:
    """从库解析角色/权限（数据库为唯一真相源，无硬编码常量兜底）。

    前提：角色/权限数据已提前录入（ensure_default_roles() 或 scripts/seed_rbac.sql）。
    查不到分配 → 403（未授权）；数据库不可用 → 403（无法解析角色）。
    """
    try:
        resolved = await RbacService.resolve(user_id, tenant_id)
    except Exception as exc:
        # 数据库不可用时无法解析角色，按未授权处理（数据须提前录入）
        raise HTTPException(
            status_code=403,
            detail=f"角色解析失败（数据库不可用或未录入分配）：{exc}",
        )
    if resolved is None:
        raise HTTPException(
            status_code=403,
            detail=f"用户 {user_id} 在租户 {tenant_id} 无角色（请先录入 agent_user_tenant 分配）",
        )
    return resolved


async def get_current_user(request: Request) -> CurrentUser:
    """FastAPI 依赖：无登录，解析上游断言的身份并查库授权。"""
    cfg = app_state.settings.security
    user_id: Optional[str] = None

    # 1) 网关 JWT：只验签，payload 仅含 user_id（不验密码、不信任其中的角色/租户）
    header = request.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        try:
            payload = jwt.decode(header[len("Bearer "):], cfg.jwt_secret, algorithms=[cfg.jwt_algorithm])
            user_id = payload.get("user_id")
        except JWTError:
            raise HTTPException(status_code=403, detail="凭证无效或过期")

    # 2) 信任头（内网/开发）
    if user_id is None and cfg.trust_headers:
        user_id = request.headers.get(cfg.user_header)

    # 3) 开发兜底（零配置本地跑通）
    if user_id is None and cfg.dev_user_id:
        user_id = cfg.dev_user_id

    if not user_id:
        raise HTTPException(status_code=401, detail="缺少身份（上游网关未注入 user_id）")

    tenant_id = request.headers.get(cfg.tenant_header) or cfg.dev_tenant_id
    role_name, scopes = await _resolve_identity(user_id, tenant_id)

    # 写入 request.state 与 contextvars，下游 require_role/require_scope、memory、audit 消费
    request.state.user_id = user_id
    request.state.tenant_id = tenant_id
    request.state.roles = [role_name]
    request.state.scopes = scopes
    user_id_ctx.set(user_id)
    tenant_id_ctx.set(tenant_id)
    return CurrentUser(user_id=user_id, tenant_id=tenant_id, roles=[role_name], scopes=scopes)
