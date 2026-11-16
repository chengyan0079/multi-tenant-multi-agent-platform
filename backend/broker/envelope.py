"""任务消息信封：key/type/header/data 四段结构，消息携带身份、消费端零信任校验。"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

from backend.broker.types import TaskType

# 信封版本：结构变更（增删字段、语义变化）时递增，消费端拒绝不认识的版本
HEADER_VERSION = 1


class MessageFormatError(ValueError):
    """消息不符合信封规范：结构缺失、字段类型非法或版本不支持。"""


@dataclass(frozen=True)
class MessageHeader:
    """消息元数据：谁发的、什么时候发的、属于哪个追踪链路。"""

    tenant_id: int | None  # 操作作用域；系统级任务为 None
    user_id: int  # 发起者；0 表示系统 / 超管内部任务
    trace_id: str | None = None  # 与 HTTP 链路串联，便于跨进程排查
    issued_at: float = field(default_factory=time.time)  # 入队时间（秒），仅用于排查
    retry_count: int = 0  # 消费重试次数，由消费端自增
    version: int = HEADER_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "trace_id": self.trace_id,
            "issued_at": self.issued_at,
            "retry_count": self.retry_count,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "MessageHeader":
        version = int(raw.get("version", HEADER_VERSION))
        if version != HEADER_VERSION:
            raise MessageFormatError(f"不支持的信封版本：{version}")
        try:
            return cls(
                tenant_id=raw.get("tenant_id"),
                user_id=int(raw["user_id"]),
                trace_id=raw.get("trace_id"),
                issued_at=float(raw.get("issued_at") or 0),
                retry_count=int(raw.get("retry_count") or 0),
                version=version,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise MessageFormatError(f"header 字段非法：{exc}") from exc


@dataclass
class TaskMessage:
    """一条异步任务消息。"""

    key: str  # 幂等键（Outbox 主键），消费端据此去重
    type: TaskType  # 消息类型
    header: MessageHeader  # 元数据（身份 / trace / 重试）
    data: dict[str, Any] = field(default_factory=dict)  # 业务载荷

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "type": self.type.value,
            "header": self.header.to_dict(),
            "data": self.data,
        }

    def to_json(self) -> bytes:
        return json.dumps(self.to_dict(), ensure_ascii=False).encode("utf-8")

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "TaskMessage":
        try:
            key = str(raw["key"])
            type_name = raw["type"]
            header = MessageHeader.from_dict(raw["header"])
        except KeyError as exc:
            raise MessageFormatError(f"信封缺字段：{exc}") from exc
        except TypeError as exc:
            raise MessageFormatError(f"信封结构非法：{exc}") from exc
        try:
            msg_type = TaskType(type_name)
        except ValueError as exc:
            raise MessageFormatError(f"未知消息类型：{type_name!r}") from exc
        data = raw.get("data") or {}
        if not isinstance(data, dict):
            raise MessageFormatError("data 必须是 JSON 对象")
        return cls(key=key, type=msg_type, header=header, data=data)

    @classmethod
    def from_json(cls, raw: bytes) -> "TaskMessage":
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise MessageFormatError(f"消息体不是合法 JSON：{exc}") from exc
        if not isinstance(parsed, dict):
            raise MessageFormatError("消息体必须是 JSON 对象")
        return cls.from_dict(parsed)
