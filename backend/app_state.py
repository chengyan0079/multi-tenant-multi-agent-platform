"""
app_state - 全局共享状态与请求上下文

启动期注入：settings / redis / db_engine / milvus / llm_factory / memory / plugin_registry /
orchestrator / checkpointer / fastapi_app。请求期（contextvars）：tenant_id / user_id / trace_id，
由 middleware 透传，保证多任务下不串号。
"""
from __future__ import annotations

import contextvars
from typing import TYPE_CHECKING, Optional

from backend.common.logger import trace_id_ctx
from backend.config import config

if TYPE_CHECKING:
    from fastapi import FastAPI
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncEngine

    from backend.core.agent_registry import AgentRegistry
    from backend.core.config_center.loader import ConfigCenterLoader
    from backend.core.llm_factory import LLMFactory
    from backend.core.memory import MemoryStore
    from backend.core.milvus_store import MemoryMilvusStore
    from backend.core.orchestrator import Orchestrator
    from backend.plugins.registry import PluginRegistry
    from backend.server.managers.nacos_discover_manager import NacosDiscoverManager


class _AppState:
    """进程级单例，各 Manager 启动时把资源写到这里。"""

    def __init__(self) -> None:
        self.settings = config
        self.redis: Optional[Redis] = None
        self.db_engine: Optional[AsyncEngine] = None
        self.milvus_client = None
        self.milvus_store: Optional[MemoryMilvusStore] = None
        self.checkpointer: Optional[AsyncPostgresSaver] = None
        self.llm_factory: Optional[LLMFactory] = None
        self.memory: Optional[MemoryStore] = None
        self.plugin_registry: Optional[PluginRegistry] = None
        self.agent_registry: Optional[AgentRegistry] = None
        self.orchestrator: Optional[Orchestrator] = None
        self.config_center: Optional[ConfigCenterLoader] = None
        self.nacos_discovery: Optional[NacosDiscoverManager] = None
        self.fastapi_app: Optional[FastAPI] = None


app_state = _AppState()

# 请求级上下文
tenant_id_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar("tenant_id", default=None)
user_id_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar("user_id", default=None)


def get_tenant_id() -> str | None:
    """当前请求的租户 id（未注入为 None）。"""
    return tenant_id_ctx.get()


def get_user_id() -> str | None:
    """当前请求的用户 id（未注入为 None）。"""
    return user_id_ctx.get()


def get_trace_id() -> str | None:
    """当前请求的链路追踪 id（未注入为 None）。"""
    return trace_id_ctx.get()
