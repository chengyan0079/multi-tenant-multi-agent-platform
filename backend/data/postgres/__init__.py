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
    AgentDbConnection,
    AgentLongTermMemory,
    AgentModel,
    AgentModelRel,
    AgentThread,
    AgentTool,
    AgentUnifiedTurn,
    ModelRegistry,
)
from backend.data.postgres.business import (
    AgentFile,
    AgentChangeRequest,
    AgentChangeReview,
    KnowledgePendingQueue,
    QaRagasEval,
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
    "AgentDbConnection",
    "AgentModel",
    "AgentModelRel",
    "ModelRegistry",
    "AgentThread",
    "AgentTool",
    "AgentLongTermMemory",
    "AgentUnifiedTurn",
    # business
    "KnowledgePendingQueue",
    "QaRagasEval",
    "AgentFile",
    "AgentChangeRequest",
    "AgentChangeReview",
    # ops
    "ConfigApproval",
    "ConfigReview",
    "ApiCallLog",
    "AgentAuditLog",
]
