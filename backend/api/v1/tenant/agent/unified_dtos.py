"""统一咨询入口请求/响应 DTO；对外 DTO 统一 extra='forbid'。"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from backend.orchestration.unified_schemas import (
    AgentCard,
    ArtifactRef,
    AttachmentRef,
    EntryField,
    EntryPayload,
)


class _Forbid(BaseModel):
    """对外 DTO 基类：拒绝额外字段，避免契约演进时静默忽略未知字段。"""

    model_config = ConfigDict(extra="forbid")


class UnifiedChatRequest(_Forbid):
    """POST /unified/chat/stream 请求体。"""

    session_id: str = Field(..., min_length=1, max_length=128, description="会话键，多轮上下文区分")
    message: str = Field(default="", max_length=2000, description="用户消息；模板问题可预填")
    agent_type: str | None = Field(default=None, description="显式通道：点卡片/模板带，跳过分类")
    entry: EntryPayload | None = Field(default=None, description="入口字段具体对象（按 spec 二次校验）")
    attachments: list[AttachmentRef] | None = Field(default=None, description="附件引用（两阶段上传返回）")
    enable_web_search: bool = Field(default=False, description="低置信度时是否启用 Web 搜索补充")


class StopChatRequest(_Forbid):
    """POST /unified/chat/stop 请求体。"""

    session_id: str = Field(..., min_length=1, description="要停止流式生成的会话键")


class AttachmentUploadResponse(_Forbid):
    """POST /unified/attachments 返回：文件引用，不建业务行、不入会话。"""

    file_ref: str  # 文件引用（后续随消息提交）
    filename: str = ""  # 原始文件名
    size: int = 0  # 文件大小（字节）
    content_type: str = ""  # MIME 类型


class SessionPageQuery(_Forbid):
    """GET /unified/sessions 分页查询参数。"""

    page: int = Field(default=1, ge=1)  # 页码
    page_size: int = Field(default=20, ge=1, le=100)  # 每页条数
    status: str | None = Field(default=None, description="按会话状态过滤（active 等）")


class CreateSessionRequest(_Forbid):
    """POST /unified/sessions 请求体；session_id 缺省由服务端生成并返回。"""

    session_id: str | None = Field(default=None, max_length=128, description="客户端预生成的会话键；缺省则服务端生成")
    title: str | None = Field(default=None, max_length=255)  # 会话标题


class SessionListItem(_Forbid):
    """会话列表单项。"""

    thread_id: str  # 会话线程 id
    session_id: str  # 会话键
    title: str  # 标题
    status: str  # 状态
    agent_type: str = ""  # 最近一次 Agent 类型
    turn_count: int = 0  # 轮数
    created_at: datetime | None = None  # 创建时间
    updated_at: datetime | None = None  # 更新时间


class TurnReplayItem(_Forbid):
    """会话回放：单条 turn（含事件 payload）。"""

    turn_index: int  # 轮次序号
    agent_type: str = ""  # Agent 类型
    event_type: str = ""  # 事件类型
    user_content: str | None = None  # 用户输入
    assistant_content: str | None = None  # 助手输出
    payload: dict[str, Any] = Field(default_factory=dict)  # 事件详情
    status: str = "success"  # 执行状态
    error_code: str | None = None  # 错误码
    create_at: datetime | None = None  # 创建时间


class SessionDetail(_Forbid):
    """GET /unified/sessions/{thread_id}：会话元信息 + 回放。"""

    thread_id: str  # 会话线程 id
    session_id: str  # 会话键
    title: str  # 标题
    status: str  # 状态
    agent_type: str = ""  # 最近一次 Agent 类型
    turn_count: int = 0  # 轮数
    created_at: datetime | None = None  # 创建时间
    updated_at: datetime | None = None  # 更新时间
    turns: list[TurnReplayItem] = Field(default_factory=list)  # 回放轮次


class ArtifactListView(_Forbid):
    """GET /unified/sessions/{thread_id}/artifacts：会话产物列表。"""

    items: list[ArtifactRef] = Field(default_factory=list)  # 产物列表
    total: int = 0  # 总数


class SessionListResponse(_Forbid):
    """GET /unified/sessions 分页响应。"""

    items: list[SessionListItem] = Field(default_factory=list)  # 会话列表
    total: int = 0  # 总数
    page: int = 1  # 页码
    page_size: int = 20  # 每页条数


class DeleteSessionResponse(_Forbid):
    """DELETE /unified/sessions/{thread_id} 响应。"""

    deleted: int = 0  # 删除数量


class AgentCapabilityView(_Forbid):
    """GET /unified/agents：单个 Agent 的能力卡片（前端渲染空态 + 模板问题）。"""

    agent_type: str  # Agent 类型
    display_name: str = ""  # 展示名
    description: str = ""  # 说明
    card: AgentCard | None = None  # 卡片配置
    templates: list[str] = Field(default_factory=list)  # 模板问题
    entry_fields: list[EntryField] = Field(default_factory=list)  # 入口表单字段
    accept_files: list[str] = Field(default_factory=list)  # 支持的文件后缀
    route_key: str = ""  # 结果页路由键
    tags: list[str] = Field(default_factory=list)  # 标签
