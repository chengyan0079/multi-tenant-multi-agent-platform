"""
MilvusManager（order=40）：启动时确保数据库与语义记忆集合就绪（参照 RAG-Ultra）。

幂等：缺失则创建（数据库 → 集合 + 索引），已存在则直接加载；无需单独初始化脚本。
向量化依赖 LLMFactory（bge-m3），故该 Manager 排在 Model(50) 之前、LLMFactory 预热后即可建集合。

连接由 `MilvusClient` 封装，本 manager 只做生命周期与装配。
"""
from __future__ import annotations

from backend.app_state import app_state
from backend.common.logger import logger
from backend.data.clients.milvus import MilvusClient
from backend.data.milvus.store import MemoryMilvusStore
from backend.server.base_manager import BaseManager, HealthInfo


class MilvusManager(BaseManager):
    async def start(self) -> None:
        cfg = app_state.settings.milvus
        client = app_state.clients.ensure(
            "milvus", lambda: MilvusClient.from_settings(cfg)
        )
        # 1) 确保数据库存在（缺失则创建）
        await client.ensure_database()
        # 2) 库级客户端 + 记忆存储（向量化复用已预热的 LLMFactory）
        await client.connect()
        store = MemoryMilvusStore(client=client.raw)
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
        # 已连接且集合已确保存在即为可用；连接断开在 start 阶段已捕获，此处仅校验就绪态
        if app_state.milvus_client is None:
            return HealthInfo(status="down", detail="milvus 未连接")
        if app_state.milvus_store is None:
            return HealthInfo(status="degraded", detail="milvus 集合未就绪")
        return HealthInfo(status="running", detail=f"db={app_state.settings.milvus.db_name}")
