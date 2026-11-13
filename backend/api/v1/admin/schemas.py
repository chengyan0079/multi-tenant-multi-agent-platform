"""超管域接口请求模型（tenant / rbac / models / config_center / agents）。"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


# ---------- 租户管理 ----------


class TenantIn(BaseModel):
    """新建租户：名称 + 主租户用户（一步建主用户并授权 tenant_admin）。"""

    name: str = Field(..., max_length=128)  # 租户名称
    # 新增租户的同时创建主租户用户并绑定 tenant_admin 角色（原子操作）
    manager: TenantManagerIn


class TenantManagerIn(BaseModel):
    """指定/更换租户管理员：username 已存在则直接绑定，否则用 password 建号再绑定。"""

    username: str = Field(..., max_length=64)  # 管理员用户名
    name: Optional[str] = Field(None, max_length=64)  # 管理员显示名
    password: Optional[str] = Field(None, max_length=128)  # 新建时的初始密码


# ---------- RBAC ----------


class RolePermsIn(BaseModel):
    """覆盖角色权限点（全量列表，服务端清空后重写）。"""

    scopes: list[str]  # 权限点全量列表


class RoleCreateIn(BaseModel):
    """新建角色：名称、说明与权限点。"""

    name: str = Field(..., max_length=64)  # 角色名
    description: Optional[str] = Field(None, max_length=255)  # 说明
    scopes: list[str] = []  # 权限点


class RoleUpdateIn(BaseModel):
    """改角色名称/说明（权限点走 PUT /roles/{id}/permissions 单独覆盖）。"""

    name: str = Field(..., max_length=64)  # 角色名
    description: Optional[str] = Field(None, max_length=255)  # 说明


class UserRoleIn(BaseModel):
    """改某用户在某租户的角色。"""

    tenant_id: int  # 目标租户
    role: str = Field(..., max_length=32)  # student / teacher / tenant_admin


# ---------- 模型配置 ----------


class ModelIn(BaseModel):
    """新增/更新模型记录的请求体（两类共用全字段结构）。"""

    model_type: str = Field(
        ..., max_length=32, description="llm / embedding / reranker / classifier"
    )  # 模型类型
    name: str = Field(..., max_length=128)  # 模型名
    provider: Optional[str] = Field(None, max_length=64)  # 供应商
    base_url: Optional[str] = Field(None, max_length=512)  # 接口 base url
    api_key: Optional[str] = Field(None, max_length=512)  # 密钥（出参脱敏）
    endpoint_path: Optional[str] = Field(None, max_length=512)  # 本地模型路径
    temperature: Optional[float] = None  # 采样温度
    timeout_s: Optional[float] = None  # 请求超时（秒）
    max_retries: Optional[int] = None  # 最大重试次数
    enabled: bool = True  # 是否启用
    sort_order: int = 0  # 排序
    description: Optional[str] = None  # 说明


# ---------- 配置中心审批流 ----------


class ConfigAddIn(BaseModel):
    """新增配置申请。"""

    namespace: str  # Nacos 命名空间
    group_id: str  # 分组
    data_id: str  # dataId
    title: Optional[str] = None  # 标题
    content_new: str  # 新内容
    content_format: str = "json"  # 内容格式
    reason: Optional[str] = None  # 申请原因


class ConfigModifyIn(BaseModel):
    """修改配置申请。"""

    namespace: str  # Nacos 命名空间
    group_id: str  # 分组
    data_id: str  # dataId
    title: Optional[str] = None  # 标题
    content_new: str  # 新内容
    content_format: str = "json"  # 内容格式
    reason: Optional[str] = None  # 申请原因


class ConfigDeleteIn(BaseModel):
    """删除配置申请。"""

    namespace: str  # Nacos 命名空间
    group_id: str  # 分组
    data_id: str  # dataId
    title: Optional[str] = None  # 标题
    reason: Optional[str] = None  # 申请原因
    # 删除不发布到 Nacos，仅作记录展示；不传则由服务端取 Nacos 当前配置的真实类型
    content_format: Optional[str] = None  # 内容格式（可空）


class RollbackRequestIn(BaseModel):
    """发起回滚申请。"""

    namespace: str  # Nacos 命名空间
    group_id: str  # 分组
    data_id: str  # dataId
    src_history_nid: int  # 回滚目标历史版本 id
    title: Optional[str] = None  # 标题
    reason: Optional[str] = None  # 申请原因
    content_format: Optional[str] = None  # 内容格式（可空）


# ---------- Agent 管理 ----------


class EnabledIn(BaseModel):
    """启停通用请求体。"""

    enabled: bool  # 是否启用


class AgentIn(BaseModel):
    """新增/更新智能体元数据的请求体。"""

    tenant_id: int  # 所属租户
    agent_type: str = Field(..., max_length=64, description="Agent 类型")
    name: str = Field(..., max_length=128)  # 名称
    description: Optional[str] = None  # 说明
    version: str = Field("1.0.0", max_length=32)  # 版本
    input_schema: Optional[str] = Field(
        None, description="输入 JSON Schema（JSON 文本）；留空表示无"
    )  # 输入 Schema


class AgentModelBindIn(BaseModel):
    """新增智能体↔模型绑定。"""

    model_id: int = Field(..., description="model_registry 主键")  # 模型 id
    is_default: bool = False  # 是否默认
    priority: int = 0  # 优先级


class AgentModelUpdateIn(BaseModel):
    """更新绑定（默认项/优先级），字段均可选，未传则保留原值。"""

    is_default: Optional[bool] = None  # 是否默认
    priority: Optional[int] = None  # 优先级
