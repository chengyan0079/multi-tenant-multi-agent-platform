"""
register - 集中注册启动项（设计文档 §10）

按 order 划分启动阶段：同 order 的 Manager 由 AppServer 用 asyncio.gather 并行启动，
不同 order 之间串行，保证依赖先后。任一失败 fail-fast 并回滚已启动项。
多副本由反向代理/LB 前置，应用本身无状态。

阶段划分（依据实际依赖）：
  10  日志          —— 其余模块依赖日志 sink 先就绪
  20  基础设施      —— Redis / PostgreSQL / Model / Plugin / RagAdapter / 可观测 / 安全，互相独立
  30  强依赖项      —— Milvus(需 Model 预热)、Checkpointer(需 PG)、Memory(需 Redis+Milvus)
  40  编排器        —— 需 Checkpointer + Model + 库
  50  HTTP 装配     —— FastAPI 挂载全部路由
  60  配置中心      —— 提示词预热需 Redis
  70  服务发现      —— 确保已监听后再对外暴露
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

    # 阶段 1：日志最先，确保后续启动日志有 sink
    server.register(LoggingManager(), 10)

    # 阶段 2：互相独立的基础设施，并行建立
    server.register(RedisManager(), 20)
    server.register(PostgreSQLManager(), 20)
    server.register(ModelManager(), 20)
    # server.register(PluginManager(), 20)   // todo
    # server.register(RagAdapterManager(), 20)    // todo
    # server.register(ObservabilityManager(), 20)   // todo
    server.register(SecurityManager(), 20)

    # 阶段 3：依赖上阶段产物（Milvus 需 Model 预热；Checkpointer 需 PG；Memory 需 Redis+Milvus）
    server.register(MilvusManager(), 30)
    # server.register(CheckpointerManager(), 30)    // todo
    # server.register(MemoryManager(), 30)    // todo

    # 阶段 4：编排器依赖 checkpointer + model + 库
    # server.register(OrchestratorManager(), 40)   // todo

    # 阶段 5：HTTP 装配
    server.register(FastAPIManager(), 50)

    # 阶段 6：配置中心热加载（提示词预热写 Redis）
    server.register(NacosConfigManager(), 60)

    # 阶段 7：服务发现放最后，确保已监听再对外暴露
    server.register(NacosDiscoverManager(), 70)

    return server
