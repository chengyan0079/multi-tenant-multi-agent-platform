"""租户管理员用户接口请求/响应模型。"""
from __future__ import annotations

from pydantic import BaseModel, Field


class TenantUserIn(BaseModel):
    """在本租户建普通用户：用户名 + 显示名 + 明文密码（一次性设定，之后不变更）。"""

    username: str = Field(..., max_length=64)
    name: str = Field(..., max_length=64)
    password: str = Field(..., max_length=128)
    role: str = Field("student", max_length=32)


class TenantUserRoleIn(BaseModel):
    """改本租户内角色（仅 student / teacher）。"""

    role: str = Field(..., max_length=32)
