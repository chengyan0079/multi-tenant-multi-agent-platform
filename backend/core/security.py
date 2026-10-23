"""
security - 护栏与 RBAC 依赖（设计文档 §9）

输入/输出护栏（违禁词、长度、注入痕迹）在接入层调用；require_role/require_scope 是 FastAPI 依赖，
路由注册时声明最小权限。认证本身在 middleware/auth.py 注入 request.state，这里只消费。
"""
from __future__ import annotations

import re
from functools import wraps
from typing import Callable, Iterable, List, Set

from fastapi import Request

from backend.core.exception import GuardrailError, TenantError

# 占位违禁词字典；真实清单走配置/外部审核插件挂载（见 plugins 设计 §15.2）
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
    """依赖工厂：要求 request.state.roles 含任一指定角色，否则 403。"""
    allowed: Set[str] = set(roles)

    async def _dep(request: Request) -> None:
        user_roles = set(getattr(request.state, "roles", []) or [])
        if not allowed & user_roles:
            raise TenantError(f"需要角色 {sorted(allowed)}，当前 {sorted(user_roles)}")

    return _dep


def require_scope(*scopes: str) -> Callable:
    """依赖工厂：要求 request.state.scopes 含全部指定 scope（最小权限）。"*" 表示全部。"""
    required: Set[str] = set(scopes)

    async def _dep(request: Request) -> None:
        user_scopes = set(getattr(request.state, "scopes", []) or [])
        if "*" in user_scopes:
            return
        if not required <= user_scopes:
            raise TenantError(f"缺少 scope {sorted(required - user_scopes)}")

    return _dep
