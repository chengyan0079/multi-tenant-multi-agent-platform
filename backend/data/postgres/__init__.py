"""模型包：仅服务于 gen_schema.py 生成 DDL，运行期不加载；业务访问走 dao 层 text()。"""

from __future__ import annotations

from backend.data.postgres.base import Base
from backend.data.postgres.auth import (
    AgentLoginLog,
    AgentRole,
    AgentRolePermission,
    AgentUserTenant,
    Menu,
    Tenant,
    User,
)
from backend.data.postgres.agent import (
    AgentCapabilityPolicy,
    AgentLongTermMemory,
    AgentModel,
    AgentModelRel,
    AgentPluginModel,
    AgentRun,
    AgentThread,
    AgentTool,
    ModelRegistry,
)
from backend.data.postgres.business import (
    AgentFile,
    Exam,
    ExamReview,
    ExamSubmission,
    InterviewQuestion,
    InterviewSession,
    KnowledgePendingQueue,
    QaResult,
    QaRagasEval,
    Question,
    ResumeReview,
    ScoringPoint,
)
from backend.data.postgres.ops import (
    AgentAuditLog,
    ApiCallLog,
    ConfigApproval,
    ConfigReview,
)


__all__ = [
    "Base",
    # auth
    "User",
    "Tenant",
    "AgentRole",
    "AgentRolePermission",
    "AgentUserTenant",
    "Menu",
    "AgentLoginLog",
    # agent
    "AgentModel",
    "AgentCapabilityPolicy",
    "AgentModelRel",
    "ModelRegistry",
    "AgentThread",
    "AgentRun",
    "AgentTool",
    "AgentPluginModel",
    "AgentLongTermMemory",
    # business
    "KnowledgePendingQueue",
    "Exam",
    "Question",
    "ScoringPoint",
    "ExamSubmission",
    "ExamReview",
    "ResumeReview",
    "InterviewQuestion",
    "InterviewSession",
    "QaResult",
    "QaRagasEval",
    "AgentFile",
    # ops
    "ConfigApproval",
    "ConfigReview",
    "ApiCallLog",
    "AgentAuditLog",
]
