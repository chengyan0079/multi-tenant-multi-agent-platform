"""超管域接口请求模型（tenant / rbac / models / config_center / agents）。"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


# ---------- 租户管理 ----------

class TenantIn(BaseModel):
    """新建租户：只填名称，租户间地位平等。"""

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


class RoleUpdateIn(BaseModel):
    """改角色名称/说明（权限点走 PUT /roles/{id}/permissions 单独覆盖）。"""

    name: str = Field(..., max_length=64)
    description: Optional[str] = Field(None, max_length=255)


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

class ConfigAddIn(BaseModel):
    """新增配置申请。"""
    namespace: str
    group_id: str
    data_id: str
    title: Optional[str] = None
    content_new: str
    content_format: str = "json"
    reason: Optional[str] = None


class ConfigModifyIn(BaseModel):
    """修改配置申请。"""
    namespace: str
    group_id: str
    data_id: str
    title: Optional[str] = None
    content_new: str
    content_format: str = "json"
    reason: Optional[str] = None


class ConfigDeleteIn(BaseModel):
    """删除配置申请。"""
    namespace: str
    group_id: str
    data_id: str
    title: Optional[str] = None
    reason: Optional[str] = None
    # 删除不发布到 Nacos，仅作记录展示；不传则由服务端取 Nacos 当前配置的真实类型
    content_format: Optional[str] = None


class RollbackRequestIn(BaseModel):
    """发起回滚申请。"""
    namespace: str
    group_id: str
    data_id: str
    src_history_nid: int
    title: Optional[str] = None
    reason: Optional[str] = None
    content_format: Optional[str] = None


# ---------- Agent 管理 ----------

class EnabledIn(BaseModel):
    """全局启停。"""
    enabled: bool


class CapabilityIn(BaseModel):
    """单条租户开通策略。"""
    agent_type: str = Field(..., max_length=64)
    enabled: bool


class AgentIn(BaseModel):
    """新增/更新智能体元数据的请求体（两类共用全字段结构）。"""

    agent_type: str = Field(..., max_length=64, description="Agent 类型（业务键，建议与代码注册一致）")
    name: str = Field(..., max_length=128)
    description: Optional[str] = None
    version: str = Field("1.0.0", max_length=32)
    enabled: bool = True
    input_schema: Optional[str] = Field(
        None, description="输入 JSON Schema（JSON 文本）；留空表示无"
    )


class AgentModelBindIn(BaseModel):
    """新增智能体↔模型绑定。"""

    model_id: int = Field(..., description="model_registry 主键")
    is_default: bool = False
    priority: int = 0


class AgentModelUpdateIn(BaseModel):
    """更新绑定（默认项/优先级），字段均可选，未传则保留原值。"""

    is_default: Optional[bool] = None
    priority: Optional[int] = None
