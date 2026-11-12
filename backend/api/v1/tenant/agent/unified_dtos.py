"""统一咨询入口请求/响应 DTO（§5.11，§8.1）。

放接入层目录，只承载 HTTP 协议边界的模型；内部契约（UnifiedEvent / RoutingDecision /
AgentOutcome 等）位于 orchestration.unified_schemas。所有对外 DTO 统一 extra='forbid'，
避免调用方传入未声明的字段悄悄被忽略。
"""
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
    """对外 DTO 基类：拒绝额外字段，便于契约演进时及早暴露破坏性改动。"""

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

    file_ref: str
    filename: str = ""
    size: int = 0
    content_type: str = ""


class SessionPageQuery(_Forbid):
    """GET /unified/sessions 分页查询参数。"""

    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)
    status: str | None = Field(default=None, description="按会话状态过滤（active 等）")


class CreateSessionRequest(_Forbid):
    """POST /unified/sessions 请求体；session_id 缺省由服务端生成并返回。"""

    session_id: str | None = Field(default=None, max_length=128, description="客户端预生成的会话键；缺省则服务端生成")
    title: str | None = Field(default=None, max_length=255)


class SessionListItem(_Forbid):
    """会话列表单项。"""

    thread_id: str
    session_id: str
    title: str
    status: str
    agent_type: str = ""
    turn_count: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None


class TurnReplayItem(_Forbid):
    """会话回放：单条 turn（含事件 payload）。"""

    turn_index: int
    agent_type: str = ""
    event_type: str = ""
    user_content: str | None = None
    assistant_content: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    status: str = "success"
    error_code: str | None = None
    create_at: datetime | None = None


class SessionDetail(_Forbid):
    """GET /unified/sessions/{thread_id}：会话元信息 + 回放。"""

    thread_id: str
    session_id: str
    title: str
    status: str
    agent_type: str = ""
    turn_count: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None
    turns: list[TurnReplayItem] = Field(default_factory=list)


class ArtifactListView(_Forbid):
    """GET /unified/sessions/{thread_id}/artifacts：会话产物列表。"""

    items: list[ArtifactRef] = Field(default_factory=list)
    total: int = 0


class SessionListResponse(_Forbid):
    """GET /unified/sessions 分页响应。"""

    items: list[SessionListItem] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 20


class DeleteSessionResponse(_Forbid):
    """DELETE /unified/sessions/{thread_id} 响应。"""

    deleted: int = 0


class AgentCapabilityView(_Forbid):
    """GET /unified/agents：单个 Agent 的能力卡片（前端渲染空态 + 模板问题）。"""

    agent_type: str
    display_name: str = ""
    description: str = ""
    card: AgentCard | None = None
    templates: list[str] = Field(default_factory=list)
    entry_fields: list[EntryField] = Field(default_factory=list)
    accept_files: list[str] = Field(default_factory=list)
    route_key: str = ""
    tags: list[str] = Field(default_factory=list)
