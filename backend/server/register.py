"""
register - 集中注册启动项（设计文档 §10）

按 order 0→100 注册各 XXManager；任一失败 fail-fast。多副本由反向代理/LB 前置，应用本身无状态。
"""
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
from backend.server.managers.observability_manager import ObservabilityManager
from backend.server.managers.orchestrator_manager import OrchestratorManager
from backend.server.managers.plugin_manager import PluginManager
from backend.server.managers.postgres_manager import PostgreSQLManager
from backend.server.managers.rag_adapter_manager import RagAdapterManager
from backend.server.managers.redis_manager import RedisManager
from backend.server.managers.security_manager import SecurityManager


def build_server() -> AppServer:
    """装配全部启动项并返回 AppServer。"""
    server = AppServer("agent-platform")
    server.register(LoggingManager(), 10)
    server.register(RedisManager(), 20)
    server.register(PostgreSQLManager(), 30)
    server.register(CheckpointerManager(), 35)
    server.register(MilvusManager(), 40)
    server.register(ModelManager(), 50)
    server.register(MemoryManager(), 55)
    server.register(PluginManager(), 60)
    server.register(RagAdapterManager(), 62)
    server.register(OrchestratorManager(), 65)
    server.register(ObservabilityManager(), 68)
    server.register(SecurityManager(), 70)
    server.register(FastAPIManager(), 100)
    # Nacos：配置中心热加载先于服务发现注册；发现放最后确保已监听再对外暴露
    server.register(NacosConfigManager(), 105)
    server.register(NacosDiscoverManager(), 110)
    return server
