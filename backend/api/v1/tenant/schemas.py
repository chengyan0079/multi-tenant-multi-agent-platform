"""租户管理员用户接口请求/响应模型。"""

from __future__ import annotations

from datetime import datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class TenantUserIn(BaseModel):
    """在本租户建普通用户：用户名 + 显示名 + 明文密码（一次性设定，之后不变更）。"""

    username: str = Field(..., max_length=64)
    name: str = Field(..., max_length=64)
    password: str = Field(..., max_length=128)
    role: str = Field("student", max_length=32)


class TenantUserRoleIn(BaseModel):
    """改本租户内角色（仅 student / teacher）。"""

    role: str = Field(..., max_length=32)


class Paged(BaseModel, Generic[T]):
    """分页响应载荷（与前端 Paged<T> 对应）。"""

    items: list[T] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 20


class UserItem(BaseModel):
    """租户用户列表项。"""

    id: int
    username: str
    name: str | None = None
    tenant_id: int
    role: str = ""
    create_at: datetime | None = None
    updated_at: datetime | None = None
