"""auth 接口请求/响应模型（见设计文档 §3）。"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class LoginIn(BaseModel):
    """登录请求体：用户名 + 密码；多租户用户可带 tenant_id 选定本次会话租户。"""

    username: str = Field(..., max_length=64, description="登录名（唯一列）")
    password: str = Field(..., max_length=128, description="明文密码，不进日志")
    tenant_id: int | None = Field(None, description="可选；不传则走 user.tenant_id 或第一个可用租户")


class MenuNode(BaseModel):
    """菜单树节点。"""

    id: int
    name: str
    path: str
    icon: str | None = None
    children: list["MenuNode"] = Field(default_factory=list)


MenuNode.model_rebuild()


class LoginData(BaseModel):
    """登录响应 data（与文档 §3.1 对齐）。"""

    token: str
    expires_in: int
    user: dict[str, Any]
    is_super_admin: bool
    is_tenant_admin: bool
    current_tenant: dict[str, Any] | None
    scopes: list[str]
    menus: list[Any]
