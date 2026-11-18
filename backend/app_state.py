"""全局共享状态与请求上下文：启动注入依赖，请求期 contextvars 透传。"""

from __future__ import annotations

import contextvars
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from backend.common.logger import ensure_trace_id, trace_id_ctx
from backend.config import config
from backend.data.clients.bundle import ClientBundle

if TYPE_CHECKING:
    from fastapi import FastAPI
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncEngine

    from backend.orchestration.agent_registry import AgentRegistry
    from backend.common.config_center.loader import ConfigCenterLoader
    from backend.common.llm.llm_factory import LLMFactory
    from backend.common.memory.memory import MemoryStore
    from backend.data.milvus.store import DocumentMilvusStore
    from backend.orchestration.orchestrator import Orchestrator
    from backend.tools.registry import PluginRegistry
    from backend.server.managers.nacos_discover_manager import NacosDiscoverManager
    from backend.server.managers.nacos_ai_manager import NacosAIManager


class _AppState:
    """进程级单例，各 Manager 启动时把资源写到这里。"""

    def __init__(self) -> None:
        self.settings = config
        # 中间件客户端容器（显式持有实例，便于整体替换做测试/多实例隔离）
        self.clients: ClientBundle = ClientBundle()
        self.redis: Optional[Redis] = None  # Redis 客户端（缓存 / 会话 / 短期记忆）
        # RabbitMQ 异步客户端（BrokerClient）；未启用/未连接时为 None
        self.broker = None
        self.db_engine: Optional[AsyncEngine] = None  # 业务库异步引擎
        self.milvus_client = None  # Milvus 客户端
        self.milvus_store: Optional[DocumentMilvusStore] = None  # 文档向量存储
        self.checkpointer: Optional[AsyncPostgresSaver] = None  # LangGraph 会话级 checkpointer
        self.llm_factory: Optional[LLMFactory] = None  # 模型工厂（LLM / embedding / reranker / classifier）
        self.memory: Optional[MemoryStore] = None  # 记忆存储（短期 / 长期）
        self.plugin_registry: Optional["PluginRegistry"] = None  # MCP / 插件注册表
        self.agent_registry: Optional[AgentRegistry] = None  # Agent 注册表
        self.orchestrator: Optional[Orchestrator] = None  # 编排器
        self.config_center: Optional[ConfigCenterLoader] = None  # 配置中心加载器
        self.nacos_discovery: Optional[NacosDiscoverManager] = None  # Nacos 服务发现
        self.nacos_ai: Optional["NacosAIManager"] = None  # Nacos AI 管理（MCP 发布）
        self.fastapi_app: Optional[FastAPI] = None  # FastAPI 应用实例
        # 运行期持有的 AppServer 实例（main.py 装配时写入），供 /health 等运维接口汇总组件状态
        self.server = None
        # 全部 manager 启动完成的时刻（AppServer.start_all 末尾写入），供 /health 与 /dashboard 算 uptime
        self.started_at: Optional[datetime] = None


app_state = _AppState()

# 请求级上下文
tenant_id_ctx: contextvars.ContextVar[int | None] = contextvars.ContextVar(
    "tenant_id", default=None
)
user_id_ctx: contextvars.ContextVar[int | None] = contextvars.ContextVar("user_id", default=None)


def get_tenant_id() -> int | None:
    """当前请求的租户 id（未注入为 None）。"""
    return tenant_id_ctx.get()


def get_user_id() -> int | None:
    """当前请求的用户 id（未注入为 None）。"""
    return user_id_ctx.get()


def get_trace_id() -> str:
    """当前请求的链路追踪 id；无上下文时按需生成并写回（与日志同源）。"""
    return ensure_trace_id()
