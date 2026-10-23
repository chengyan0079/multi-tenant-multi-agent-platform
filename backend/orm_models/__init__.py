"""models 包：SQLAlchemy 模型层 + 会话助手。"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app_state import app_state
from backend.orm_models.base import Base
from backend.orm_models.threads import AgentThread
from backend.orm_models.runs import AgentRun
from backend.orm_models.messages import AgentMessage
from backend.orm_models.plugins import AgentPluginModel
from backend.orm_models.tools import AgentTool
from backend.orm_models.escalations import AgentEscalation
from backend.orm_models.memory import AgentLongTermMemory
from backend.orm_models.audit import AgentAuditLog
from backend.orm_models.config_center import ConfigChangeRequest, ConfigReview
from backend.orm_models.api_log import ApiCallLog
from backend.orm_models.rbac import AgentRole, AgentRolePermission, AgentUserTenant


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """从 app_state.db_engine 构造 sessionmaker（未就绪时断言失败）。"""
    assert app_state.db_engine is not None, "db_engine 未初始化"
    return async_sessionmaker(app_state.db_engine, expire_on_commit=False)


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """请求/事务作用域会话（自动提交/回滚）。"""
    async with get_sessionmaker()() as session:
        yield session


__all__ = [
    "Base",
    "AgentThread",
    "AgentRun",
    "AgentMessage",
    "AgentPluginModel",
    "AgentTool",
    "AgentEscalation",
    "AgentLongTermMemory",
    "AgentAuditLog",
    "ConfigChangeRequest",
    "ConfigReview",
    "ApiCallLog",
    "AgentRole",
    "AgentRolePermission",
    "AgentUserTenant",
    "get_sessionmaker",
    "session_scope",
]
