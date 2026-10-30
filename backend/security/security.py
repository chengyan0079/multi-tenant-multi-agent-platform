"""
security - 护栏与 RBAC 依赖（设计文档 §9）

输入/输出护栏（违禁词、长度、注入痕迹）在接入层调用；require_role/require_scope/require_tenant
是 FastAPI 依赖，路由注册时声明最小权限。身份解析在 middleware/auth.py，这里的守卫直接依赖
get_current_user，不读 request.state——router 级依赖先于路由函数执行，那时 state 还没写入。
"""
from __future__ import annotations

import re
from functools import wraps
from typing import Callable, Iterable, List, Set

from fastapi import Depends, HTTPException

from backend.middleware.auth import CurrentUser, get_current_user
from backend.security.rbac import VALID_SCOPES
from backend.observability.exception import GuardrailError, TenantError

# //todo 占位违禁词字典；真实清单走配置/外部审核插件挂载（见 plugins 设计 §15.2）
_FORBIDDEN: Set[str] = set()
_INJECT_HINT = re.compile(r"(ignore\s+(previous|above|all)\s+instructions|disregard\s+(the\s+)?system)", re.I)


def check_input(text: str) -> str:
    """输入护栏：违禁词 + Prompt 注入痕迹 + 长度。命中抛 GuardrailError。"""
    if not text:
        return text
    if len(text) > 20000:
        raise GuardrailError("输入超长")
    for word in _FORBIDDEN:
        if word and word in text:
            raise GuardrailError("输入含违禁词")
    if _INJECT_HINT.search(text):
        raise GuardrailError("检测到 Prompt 注入尝试")
    return text


def check_output(text: str) -> str:
    """输出护栏：生成后二次过滤。当前仅做违禁词扫描，命中抛 GuardrailError。"""
    if not text:
        return text
    for word in _FORBIDDEN:
        if word and word in text:
            raise GuardrailError("输出含违禁词")
    return text


def require_role(*roles: str) -> Callable:
    """依赖工厂：要求 current.roles 含任一指定角色，否则 403。

    直接依赖 get_current_user（FastAPI 同请求内缓存，不会重复查库），不再读
    request.state——router 级依赖先于路由函数执行，那时 state 还没写入。
    """
    allowed: Set[str] = set(roles)

    async def _dep(current: CurrentUser = Depends(get_current_user)) -> None:
        user_roles = set(current.roles or [])
        if not allowed & user_roles:
            raise TenantError(f"需要角色 {sorted(allowed)}，当前 {sorted(user_roles)}")

    return _dep


def require_super_admin() -> Callable:
    """依赖工厂：要求当前用户是平台超管（全局唯一，只做基建、不进业务链路）。

    admin 路由组在装配处统一声明本依赖，判定口径与登录响应里的 is_super_admin 一致，
    由 RbacService 从库里解出，这里只读布尔值，不在各处重复比角色名或 role_id。
    """

    async def _dep(current: CurrentUser = Depends(get_current_user)) -> None:
        if not current.is_super_admin:
            raise HTTPException(status_code=403, detail="仅平台管理员可操作")

    return _dep


def require_tenant() -> Callable:
    """依赖工厂：要求请求带租户，挡下超管对业务接口的调用。

    业务路由组在装配处统一声明。超管没有租户上下文，调 /chat、/threads 这类接口
    会落到这里直接 403，不会出现「超管以某个租户身份悄悄发起业务」的情况。
    """

    async def _dep(current: CurrentUser = Depends(get_current_user)) -> None:
        if current.tenant_id is None:
            raise HTTPException(status_code=403, detail="平台超管无租户上下文")

    return _dep


def require_tenant_admin() -> Callable:
    """依赖工厂：要求当前用户是租户管理员（tenant_admin 角色），不含超管。

    与 require_super_admin / require_tenant 一致：通过 Depends(get_current_user) 取得已解析身份，
    只读 current.is_tenant_admin，不重复比角色名。
    """

    async def _dep(current: CurrentUser = Depends(get_current_user)) -> None:
        if not current.is_tenant_admin:
            raise HTTPException(status_code=403, detail="仅本租户管理员可操作")

    return _dep


def require_admin_or_tenant_admin() -> Callable:
    """依赖工厂：要求平台超管或租户管理员（管理面「跨租户/本租户」双视角入口）。

    只做准入，不决定数据范围：超管无租户（tenant_id=None）可查全局，租户管理员
    有租户上下文只能查本租户，范围由各端点按 current.is_super_admin 自行收敛。
    """

    async def _dep(current: CurrentUser = Depends(get_current_user)) -> None:
        if not (current.is_super_admin or current.is_tenant_admin):
            raise HTTPException(status_code=403, detail="仅平台超管或租户管理员可操作")

    return _dep


def require_scope(*scopes: str) -> Callable:
    """依赖工厂：要求 current.scopes 含全部指定 scope（最小权限）。

    直接依赖 get_current_user（FastAPI 同请求内缓存，不会重复查库），不再读
    request.state——router 级依赖先于路由函数执行，那时 state 还没写入。
    """
    required: Set[str] = set(scopes)
    # 校验声明合法：拼写错误的 scope 在依赖注册期即暴露
    for s in required:
        # Scope 不再是 Enum，用合法权限点集合校验声明合法性（防笔误绕过鉴权）
        if s not in VALID_SCOPES:
            raise ValueError(f"未知 scope: {s}")

    async def _dep(current: CurrentUser = Depends(get_current_user)) -> None:
        user_scopes = set(current.scopes or [])
        if not required <= user_scopes:
            raise TenantError(f"缺少 scope {sorted(required - user_scopes)}")

    return _dep
