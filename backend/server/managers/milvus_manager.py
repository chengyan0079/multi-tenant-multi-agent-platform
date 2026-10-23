"""
MilvusManager（order=40）：启动时确保数据库与语义记忆集合就绪（参照 RAG-Ultra）。

幂等：缺失则创建（数据库 → 集合 + 索引），已存在则直接加载；无需单独初始化脚本。
向量化依赖 LLMFactory（bge-m3），故该 Manager 排在 Model(50) 之前、LLMFactory 预热后即可建集合。
"""
from __future__ import annotations

from pymilvus import AsyncMilvusClient

from backend.app_state import app_state
from backend.common.logger import logger
from backend.core.milvus_store import MemoryMilvusStore
from backend.server.base_manager import BaseManager


async def _ensure_database(uri: str, db_name: str) -> None:
    """确保 Milvus 数据库存在（连默认库做管理操作；缺失则创建）。"""
    admin = AsyncMilvusClient(uri=uri)
    try:
        existing = await admin.list_databases()
        if db_name in existing:
            logger.info(f"Milvus 数据库已存在: {db_name}")
        else:
            await admin.create_database(db_name)
            logger.info(f"已创建 Milvus 数据库: {db_name}")
    finally:
        await admin.close()


class MilvusManager(BaseManager):
    async def start(self) -> None:
        cfg = app_state.settings.milvus
        uri = f"http://{cfg.host}:{cfg.port}"
        # 1) 确保数据库存在（缺失则创建）
        await _ensure_database(uri, cfg.db_name)
        # 2) 库级客户端 + 记忆存储（向量化复用已预热的 LLMFactory）
        client = AsyncMilvusClient(uri=uri, db_name=cfg.db_name, token=cfg.token or None)
        store = MemoryMilvusStore(client=client)
        # 3) 确保集合存在：不存在则创建 + 索引，已存在则直接加载（幂等）
        await store.ensure_collection()
        app_state.milvus_client = client
        app_state.milvus_store = store
        logger.info(f"Milvus 就绪（db={cfg.db_name}, collection={cfg.collection}）")

    async def stop(self) -> None:
        if app_state.milvus_client is not None:
            await app_state.milvus_client.close()
            app_state.milvus_client = None
        app_state.milvus_store = None
