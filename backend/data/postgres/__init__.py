"""模型包：**只服务于 `scripts/gen_schema.py` 生成 DDL，运行期不加载**。

按域分四个子包：
- `auth`     登录鉴权：用户/租户、角色权限、菜单、登录日志
- `agent`    Agent 运行时：Agent 定义、模型关联与注册、线程/消息/运行/工具/插件/记忆/升级
- `business` 业务元数据：考试、简历审查、面试、QA、知识待入队
- `ops`      运维：配置变更、审计日志、接口调用日志

业务代码不要从这里 import：数据访问统一走 `backend/data/dao/` 的 `text()`，
连接管理在 `backend/data/sql/`，审计列注入在 `backend/data/sql/audit.py`。
"""
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
    AgentEscalation,
    AgentLongTermMemory,
    AgentMessage,
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
    QaSession,
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
    "AgentMessage",
    "AgentRun",
    "AgentTool",
    "AgentPluginModel",
    "AgentLongTermMemory",
    "AgentEscalation",
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
    "QaSession",
    "AgentFile",
    # ops
    "ConfigApproval",
    "ConfigReview",
    "ApiCallLog",
    "AgentAuditLog",
]
