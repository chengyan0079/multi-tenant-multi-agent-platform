"""
MilvusManager（order=40）：启动时确保数据库与 RAG 文档集合就绪，并对外提供连接活性探测。

生命周期职责：
1. 确保数据库存在（缺失则创建，用一次性 admin 客户端，不占用业务连接）；
2. 库级客户端由 MilvusClient 封装（已含真实探活 health_check / verify）；
3. 绑定 RAG 文档向量存储 DocumentMilvusStore，确保集合存在并加载到内存。
全程幂等，无需单独初始化脚本。

本 manager 的核心价值是「连接活性检测」：health() 走 MilvusClient.health_check() 真实握手
（list_databases），而非仅看对象是否非空；连接断开/不可达时即报 down，供 /health 与启动后状态展示。
"""
from __future__ import annotations

from backend.app_state import app_state
from backend.common.logger import logger
from backend.data.clients.milvus import MilvusClient
from backend.data.milvus.store import DocumentMilvusStore
from backend.server.base_manager import BaseManager, HealthInfo


class MilvusManager(BaseManager):
    async def start(self) -> None:
        cfg = app_state.settings.milvus
        # 连接由 MilvusClient 封装，注册进 clients 容器便于整体替换/测试
        client = app_state.clients.ensure(
            "milvus", lambda: MilvusClient.from_settings(cfg)
        )
        # 1) 确保数据库存在（缺失则创建）
        await client.ensure_database()
        # 2) 建连 + 绑定 RAG 文档存储
        await client.connect()
        store = DocumentMilvusStore(client=client.raw)
        # 3) 确保集合存在：不存在则创建 + 索引，已存在则直接加载（幂等）
        await store.ensure_collection()
        app_state.milvus_client = client.raw
        app_state.milvus_store = store
        logger.info(f"Milvus 就绪（db={cfg.db_name}, collection={cfg.collection}）")

    async def stop(self) -> None:
        if app_state.clients.has("milvus"):
            await app_state.clients.get_as("milvus", MilvusClient).close()
        app_state.milvus_client = None
        app_state.milvus_store = None

    async def health(self) -> HealthInfo:
        # 连接活性：用 MilvusClient 封装的真实探活（list_databases 握手）
        try:
            client = app_state.clients.get_as("milvus", MilvusClient)
        except Exception:  # noqa: BLE001 - 客户端未初始化即视为 down
            return HealthInfo(status="down", detail="milvus 客户端未初始化")
        if not await client.health_check():
            return HealthInfo(status="down", detail="milvus 连接探活失败（地址/端口/凭据或网络不可达）")
        if app_state.milvus_store is None:
            return HealthInfo(status="degraded", detail="milvus 集合未就绪")
        return HealthInfo(status="running", detail=f"db={app_state.settings.milvus.db_name}")
