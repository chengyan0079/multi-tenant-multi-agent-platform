"""统一咨询入口内部契约：State / 编排层 / dispatch 使用的 Pydantic 模型。"""
from enum import Enum
from typing import Any, Literal

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, create_model


# --------------------------------------------------------------------------- #
# 路由 / 意图
# --------------------------------------------------------------------------- #
class InitValuesPayload(BaseModel):
    """LLM 抽取的入口字段（D17：具体对象，extra='forbid'）。"""

    model_config = ConfigDict(extra="forbid")
    target_position: str | None = None
    exam_id: str | None = None
    resume_review_id: str | None = None


class RoutingDecision(BaseModel):
    """UnifiedState.routing 与 turn 表 routing 列的统一结构。"""

    label: str
    agent_type: str
    source: str  # explicit | rule | llm | fallback
    confidence: float = 0.0
    reason: str = ""
    execution_mode: str = "agent"  # agent | clarify | rule | pipeline
    fallback_used: bool = False
    spec_version: str = ""
    init_values: InitValuesPayload = Field(default_factory=InitValuesPayload)
    error_code: str | None = None  # 路由阶段即判定不可用（如显式请求已停用 Agent）


class IntentResponse(BaseModel):
    """get_structured_llm 结构化分类输出。"""

    model_config = ConfigDict(extra="forbid")
    label: str
    reason: str = ""
    confidence: float = 0.0
    init_values: InitValuesPayload = Field(default_factory=InitValuesPayload)


# --------------------------------------------------------------------------- #
# 入口字段
# --------------------------------------------------------------------------- #
class EntryFieldType(str, Enum):
    STR = "str"
    INT = "int"
    FLOAT = "float"
    BOOL = "bool"
    UUID = "uuid"
    ENUM = "enum"


class EntryField(BaseModel):
    """spec.entry_fields 的单项定义。"""

    name: str
    label: str
    type: EntryFieldType
    required: bool = False
    default: Any | None = None
    options: list[str] | None = None  # type=enum 时的可选项


class EntryFieldValue(BaseModel):
    """EntryPayload 中的单条值（值统一以字符串表达，由动态模型做二次校验）。"""

    name: str
    value: str = ""


class EntryPayload(BaseModel):
    """UnifiedChatRequest.entry；按 spec 生成的动态模型二次校验。"""

    model_config = ConfigDict(extra="forbid")
    fields: list[EntryFieldValue] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# 附件 / 展示
# --------------------------------------------------------------------------- #
class AttachmentRef(BaseModel):
    """上传附件引用（UnifiedChatRequest.attachments）。"""

    file_ref: str
    filename: str = ""
    size: int = 0
    content_type: str = ""


class AgentCard(BaseModel):
    icon: str = ""  # 图标
    badge: str = ""  # 角标
    sort_order: int = 0  # 排序
    action_label: str = ""  # 卡片按钮文案


class MenuSpec(BaseModel):
    name: str = ""  # 菜单名
    path: str = ""  # 路由
    icon: str = ""  # 图标
    sort_order: int = 0  # 排序
    parent_path: str = ""  # 父级路由
    scope: str = ""  # 菜单可见 scope


class ProgressLabel(BaseModel):
    node: str  # 节点名
    text: str  # 进度文案


# --------------------------------------------------------------------------- #
# Pipeline
# --------------------------------------------------------------------------- #
class PipelineStep(BaseModel):
    step: str
    agent_type: str
    label: str = ""
    desc: str = ""
    route_key: str = ""
    tip: str = ""


class PipelinePlan(BaseModel):
    title: str = ""
    intro: str = ""
    steps: list[PipelineStep] = Field(default_factory=list)


class ArtifactRef(BaseModel):
    """业务产物引用（turn payload 承载）。"""

    artifact_type: str
    artifact_id: str
    route_key: str = ""


class PipelineCarry(BaseModel):
    content: str = ""
    artifacts: list[ArtifactRef] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# 记忆
# --------------------------------------------------------------------------- #
class ShortTermTurn(BaseModel):
    turn_id: str
    role: str
    content: str
    agent_type: str = ""
    event_type: str = ""
    create_at: datetime | None = None


class LongTermMemoryBlock(BaseModel):
    id: str = ""
    agent_id: str = ""
    block: str = ""  # summary | fact | preference
    content: str = ""
    embedding_id: str = ""
    create_at: datetime | None = None


# --------------------------------------------------------------------------- #
# SSE 事件（判别联合）
# --------------------------------------------------------------------------- #
class _EventBase(BaseModel):
    """SSE 事件基类；具体事件各自声明 event_type 判别字段。"""


class RoutingDecisionEvent(_EventBase):
    event_type: Literal["routing_decision"] = "routing_decision"
    agent_type: str = ""
    agent_display: str = ""
    source: str = ""
    confidence: float = 0.0
    reason: str = ""
    execution_mode: str = ""
    spec_version: str = ""


class TokenEvent(_EventBase):
    event_type: Literal["token"] = "token"
    content: str = ""


class ProgressEvent(_EventBase):
    event_type: Literal["progress"] = "progress"
    stage: str = ""


class MetaEvent(_EventBase):
    event_type: Literal["meta"] = "meta"
    thread_id: str = ""
    turn_id: str = ""
    turn_index: int = 0
    answer_mode: str | None = None
    confidence: float | None = None
    sources: list[str] | None = None


class GuidanceEvent(_EventBase):
    event_type: Literal["guidance"] = "guidance"
    message: str = ""
    action_label: str = ""
    route_key: str = ""
    code: str | None = None


class PipelinePlanEvent(_EventBase):
    event_type: Literal["pipeline_plan"] = "pipeline_plan"
    plan: PipelinePlan | None = None


class PipelineStepResultEvent(_EventBase):
    event_type: Literal["pipeline_step_result"] = "pipeline_step_result"
    step: str = ""
    agent_type: str = ""
    content: str = ""
    artifacts: list[ArtifactRef] = Field(default_factory=list)


class PipelineResultEvent(_EventBase):
    event_type: Literal["pipeline_result"] = "pipeline_result"
    content: str = ""
    artifacts: list[ArtifactRef] = Field(default_factory=list)
    trace_id: str = ""


class TaskStartedEvent(_EventBase):
    event_type: Literal["task_started"] = "task_started"
    artifact_type: str = ""
    artifact_id: str = ""
    task_id: str = ""


class TaskProgressEvent(_EventBase):
    event_type: Literal["task_progress"] = "task_progress"
    stage: str = ""
    percent: float | None = None
    detail: str | None = None


class TaskResultEvent(_EventBase):
    event_type: Literal["task_result"] = "task_result"
    artifact_type: str = ""
    artifact_id: str = ""
    summary: str = ""
    route_key: str = ""


class ReviewRequiredEvent(_EventBase):
    event_type: Literal["review_required"] = "review_required"
    artifact_id: str = ""
    route_key: str = ""


class StoppedEvent(_EventBase):
    event_type: Literal["stopped"] = "stopped"


class DoneEvent(_EventBase):
    event_type: Literal["done"] = "done"


class ErrorEvent(_EventBase):
    event_type: Literal["error"] = "error"
    code: str = ""
    message: str = ""


UnifiedEventPayload = (
    RoutingDecisionEvent
    | TokenEvent
    | ProgressEvent
    | MetaEvent
    | GuidanceEvent
    | PipelinePlanEvent
    | PipelineStepResultEvent
    | PipelineResultEvent
    | TaskStartedEvent
    | TaskProgressEvent
    | TaskResultEvent
    | ReviewRequiredEvent
    | StoppedEvent
    | DoneEvent
    | ErrorEvent
)


class UnifiedEvent(BaseModel):
    """SSE 帧统一模型；payload 为判别联合（按 event_type 分发具体事件）。"""

    model_config = ConfigDict(extra="forbid")
    event_type: str
    payload: UnifiedEventPayload = Field(discriminator="event_type")


# --------------------------------------------------------------------------- #
# dispatch 输出
# --------------------------------------------------------------------------- #
class StatePatch(BaseModel):
    answer_mode: str | None = None
    confidence: float | None = None
    sources: list[str] = Field(default_factory=list)


class QaResultRef(BaseModel):
    """PersistencePayload.qa_result 引用（§5.11 表外引用，最小定义）。"""

    qa_result_id: str
    trace_id: str | None = None


class PersistencePayload(BaseModel):
    artifact: ArtifactRef | None = None
    qa_result: QaResultRef | None = None
    touch: bool = True


class AgentOutcome(BaseModel):
    """dispatch 返回的统一结果。"""

    content: str = ""
    events: list[UnifiedEvent] = Field(default_factory=list)
    state_patch: StatePatch | None = None
    persistence: PersistencePayload | None = None


# --------------------------------------------------------------------------- #
# 动态入口校验模型
# --------------------------------------------------------------------------- #
_TYPE_MAP: dict[EntryFieldType, type] = {
    EntryFieldType.STR: str,
    EntryFieldType.INT: int,
    EntryFieldType.FLOAT: float,
    EntryFieldType.BOOL: bool,
    EntryFieldType.UUID: uuid.UUID,
    EntryFieldType.ENUM: str,  # 实际约束由 options -> Enum 决定
}


def _build_enum_type(agent_type: str, field_name: str, options: list[str]) -> type:
    """为 enum 类型入口字段生成值受限于 options 的 Enum 类。"""
    members = {f"v{i}": opt for i, opt in enumerate(options)}
    return Enum(f"EntryEnum_{agent_type}_{field_name}", members)


_entry_values_cache: dict[str, type[BaseModel]] = {}


def build_entry_values_model(
    entry_fields: list[EntryField] | tuple[EntryField, ...],
    agent_type: str,
) -> type[BaseModel]:
    """按 spec.entry_fields 生成 EntryValues_<agent_type> 校验模型（D17 约定 2）。

    - type 映射到 Python 类型；options 存在时改用受限于可选项的 Enum；
    - required 决定字段是否必填，非必填统一为 Optional 并以 default 兜底；
    - 结果按 agent_type 缓存，新增 Agent 不需改统一层。
    """
    if agent_type in _entry_values_cache:
        return _entry_values_cache[agent_type]

    fields: dict[str, Any] = {}
    for ef in entry_fields:
        if ef.type == EntryFieldType.ENUM and ef.options:
            ann: Any = _build_enum_type(agent_type, ef.name, ef.options)
        else:
            ann = _TYPE_MAP.get(ef.type, str)

        if ef.required:
            default: Any = ... if ef.default is None else ef.default
        else:
            ann = ann | None
            default = ef.default

        fields[ef.name] = (ann, Field(default, description=ef.label))

    model = create_model(
        f"EntryValues_{agent_type}",
        __base__=BaseModel,
        __config__=ConfigDict(extra="forbid", use_enum_values=True),
        **fields,
    )
    _entry_values_cache[agent_type] = model
    return model
