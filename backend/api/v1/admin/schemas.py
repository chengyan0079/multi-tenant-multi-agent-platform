"""超管域接口请求模型（tenant / rbac / models / config_center / agents）。"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


# ---------- 租户管理 ----------

class TenantIn(BaseModel):
    """新建租户：is_primary 不可指定，恒 false。"""

    name: str = Field(..., max_length=128)


class TenantUpdate(BaseModel):
    """改名 / 启停（NULL 表示不改动）。"""

    name: Optional[str] = Field(None, max_length=128)
    enabled: Optional[bool] = None


class TenantManagerIn(BaseModel):
    """指定/更换租户管理员：username 已存在则直接绑定，否则用 password 建号再绑定。"""

    username: str = Field(..., max_length=64)
    name: Optional[str] = Field(None, max_length=64)
    password: Optional[str] = Field(None, max_length=128)


# ---------- RBAC ----------

class RolePermsIn(BaseModel):
    """覆盖角色权限点（全量列表，服务端清空后重写）。"""

    scopes: list[str]


class RoleCreateIn(BaseModel):
    """新建角色：名称、说明与权限点。"""

    name: str = Field(..., max_length=64)
    description: Optional[str] = Field(None, max_length=255)
    scopes: list[str] = []


class UserRoleIn(BaseModel):
    """改某用户在某租户的角色。"""

    tenant_id: int
    role: str = Field(..., max_length=32)  # student / teacher / tenant_admin


# ---------- 模型配置 ----------

class ModelIn(BaseModel):
    """新增/更新模型记录的请求体（两类共用全字段结构）。"""

    model_type: str = Field(..., max_length=32, description="llm / embedding / reranker / classifier")
    name: str = Field(..., max_length=128)
    provider: Optional[str] = Field(None, max_length=64)
    base_url: Optional[str] = Field(None, max_length=512)
    api_key: Optional[str] = Field(None, max_length=512)
    endpoint_path: Optional[str] = Field(None, max_length=512)
    temperature: Optional[float] = None
    timeout_s: Optional[float] = None
    max_retries: Optional[int] = None
    enabled: bool = True
    sort_order: int = 0
    description: Optional[str] = None


# ---------- 配置中心审批流 ----------

class CreateRequestIn(BaseModel):
    """发起配置变更申请。"""
    namespace: str
    group_id: str
    data_id: str
    domain: str = "prompt"
    op_type: int  # 1=新增 2=修改 3=删除
    title: Optional[str] = None
    content_new: Optional[str] = None
    content_format: str = "json"
    reason: Optional[str] = None


class RollbackRequestIn(BaseModel):
    """发起回滚申请。"""
    namespace: str
    group_id: str
    data_id: str
    domain: str = "prompt"
    src_history_nid: int
    title: Optional[str] = None
    reason: Optional[str] = None


class ReviewIn(BaseModel):
    """复核（通过/驳回）。"""
    action: int  # 1=通过 2=驳回
    comment: Optional[str] = None


# ---------- Agent 管理 ----------

class EnabledIn(BaseModel):
    """全局启停。"""
    enabled: bool


class CapabilityIn(BaseModel):
    """单条租户开通策略。"""
    agent_type: str = Field(..., max_length=64)
    enabled: bool
