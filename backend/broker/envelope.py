"""任务消息信封：所有入队消息统一结构，必带 tenant_id / user_id 做租户隔离与鉴权。

消息体（而非仅 topic）携带身份，是因为消费端需"零信任"地按 tenant_id / user_id 重走
权限校验（见 broker/security.py），不能凭 topic 假设调用者有权。
"""
from __future__ import annotations

import json
import uuid6
from dataclasses import dataclass, field
from typing import Any


@dataclass
class TaskMessage:
    """一条异步任务消息。"""

    type: str  # 业务类型，路由到对应 handler（如 "audit.flush"）
    tenant_id: int | None  # 操作作用域（目标租户）；系统级任务可为 None
    user_id: int  # 发起者；0 表示系统 / 超管内部任务
    payload: dict[str, Any] = field(default_factory=dict)
    retry_count: int = 0  # 重试次数（死信重试时递增）
    message_id: str = ""  # 稳定 id，用于去重 / 追溯

    def to_dict(self) -> dict:
        """转 dict（不含 message_id，message_id 由 Outbox id 承担）。"""
        return {
            "type": self.type,
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "payload": self.payload,
        }

    def to_json(self) -> bytes:
        return json.dumps(
            {
                "type": self.type,
                "tenant_id": self.tenant_id,
                "user_id": self.user_id,
                "payload": self.payload,
                "retry_count": self.retry_count,
                "message_id": self.message_id or uuid6.uuid7().hex,
            },
            ensure_ascii=False,
        ).encode("utf-8")

    @classmethod
    def from_json(cls, raw: bytes) -> "TaskMessage":
        d = json.loads(raw.decode("utf-8"))
        return cls(
            type=d["type"],
            tenant_id=d.get("tenant_id"),
            user_id=d["user_id"],
            payload=d.get("payload", {}),
            retry_count=d.get("retry_count", 0),
            message_id=d.get("message_id", ""),
        )
