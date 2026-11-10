"""集中注册启动项：按 order 分阶段并行/串行启动，失败 fail-fast 并回滚。"""

from __future__ import annotations

from backend.server.app_server import AppServer
from backend.server.managers.checkpointer_manager import CheckpointerManager
from backend.server.managers.fastapi_manager import FastAPIManager
from backend.server.managers.logging_manager import LoggingManager
from backend.server.managers.memory_manager import MemoryManager
from backend.server.managers.milvus_manager import MilvusManager
from backend.server.managers.model_manager import ModelManager
from backend.server.managers.nacos_config_manager import NacosConfigManager
from backend.server.managers.nacos_discover_manager import NacosDiscoverManager
from backend.server.managers.nacos_ai_manager import NacosAIManager
from backend.server.managers.observability_manager import ObservabilityManager
from backend.server.managers.orchestrator_manager import OrchestratorManager
from backend.server.managers.plugin_manager import PluginManager
from backend.server.managers.postgres_manager import PostgreSQLManager
from backend.server.managers.redis_manager import RedisManager
from backend.server.managers.security_manager import SecurityManager
from backend.server.managers.broker_manager import BrokerManager
from backend.server.managers.scheduler_manager import SchedulerManager
from backend.config import config


def build_server() -> AppServer:
    """装配全部启动项并返回 AppServer。"""
    server = AppServer("agent-platform")

    # 阶段 1：日志最先，确保后续启动日志有 sink
    server.register(LoggingManager(), 10)

    # 阶段 2：互相独立的基础设施，并行建立
    server.register(RedisManager(), 20)
    server.register(PostgreSQLManager(), 20)
    server.register(ModelManager(), 20)
    server.register(ObservabilityManager(), 20)
    server.register(SecurityManager(), 20)

    # 消息队列：默认不启用（RABBITMQ_ENABLED=false），启用才注册，避免无 broker 阻断启动
    if config.broker.enabled:
        server.register(BrokerManager(), 20)

    # 定时任务（通用定时器）：随应用启动，不依赖 broker。
    # 现有 job：HITL 转人工超时提醒（经 Outbox，broker 关时缓冲不丢）、resume 评审超时兜底标 failed。
    server.register(SchedulerManager(), 30)
    # 插件注册表依赖 PG 查询，必须在阶段 20 之后
    server.register(PluginManager(), 30)

    # 阶段 3：依赖上阶段产物（Milvus 需 Model 预热；Checkpointer 需 PG；Memory 需 Redis+Milvus）
    server.register(MilvusManager(), 30)
    server.register(CheckpointerManager(), 30)
    server.register(MemoryManager(), 30)

    # 阶段 4：编排器依赖 checkpointer + model + 库
    server.register(OrchestratorManager(), 40)

    # 阶段 5：HTTP 装配
    server.register(FastAPIManager(), 50)

    # 阶段 6：配置中心热加载（提示词预热写 Redis）
    server.register(NacosConfigManager(), 60)

    # 阶段 7：服务发现放最后，确保已监听再对外暴露
    server.register(NacosDiscoverManager(), 70)
    # Nacos AI：发布本平台 MCP Server（release_mcp_server），放在发现注册之后
    server.register(NacosAIManager(), 75)

    return server
