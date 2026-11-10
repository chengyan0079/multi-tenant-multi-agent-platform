"""业务消息类型枚举（type 唯一来源，域.动作命名）；枚举值即队列名/handler 键/Outbox topic。"""

from __future__ import annotations

from enum import Enum


class TaskType(str, Enum):
    """全部业务消息类型。"""

    AGENT_RUN = "agent.run"
    QA_PARSE = "qa.parse"
    QA_RAGAS_REVIEW = "qa.ragas_review"
    RESUME_REVIEW = "resume.review"
    EXAM_REVIEW = "exam.review"
    NOTIFY_SEND = "notify.send"
    AUDIT_FLUSH = "audit.flush"

    def __str__(self) -> str:
        # str 枚举默认输出 "TaskType.AGENT_RUN"，统一成枚举值便于日志与队列命名
        return self.value
