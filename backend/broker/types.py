"""业务消息类型枚举：type 的唯一来源。

命名约定 `域.动作`（全小写、点分隔）。枚举值同时作为队列名、handler 键与 Outbox topic，
拼写错误在编码期就被类型系统拦住，不再需要运行时正则校验。
新增类型必须同时补 QueueSpec 与 handler，启动期会做一致性对账。
"""
from __future__ import annotations

from enum import Enum


class TaskType(str, Enum):
    """全部业务消息类型。"""

    AGENT_RUN = "agent.run"
    DOC_PARSE = "doc.parse"
    RESUME_REVIEW = "resume.review"
    KNOWLEDGE_REINDEX = "knowledge.reindex"
    NOTIFY_SEND = "notify.send"
    AUDIT_FLUSH = "audit.flush"
    CONFIG_REFRESH = "config.refresh"

    def __str__(self) -> str:
        # str 枚举默认输出 "TaskType.AGENT_RUN"，统一成枚举值便于日志与队列命名
        return self.value
