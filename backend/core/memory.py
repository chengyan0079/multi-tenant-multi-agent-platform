"""
memory - 分层记忆抽象（设计文档 §6.1）

短期 Redis 滚动窗口 / 长期 PG Letta 式分页 / 语义 Milvus。本文件定义统一接口与基于 Redis 的
短期记忆实现，长期与语义落点后续接 models + milvus_store。单 Agent 直接复用，无需自建。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from backend.app_state import app_state, get_tenant_id
from backend.common.logger import get_logger

logger = get_logger("memory")

SHORT_TTL_S = 60 * 60 * 24  # 短期会话窗口保留 1 天


class MemoryStore:
    """记忆存储：短期（Redis）+ 长期/语义（后续接 PG/Milvus）。"""

    async def start(self) -> None:
        # 资源由 RedisManager / PostgresManager / MilvusManager 注入 app_state，此处仅做可用性检查
        if app_state.redis is None:
            logger.warning("Redis 未就绪，短期记忆降级为无操作")

    async def push_short(self, thread_id: str, message: Dict[str, Any]) -> None:
        """追加一条短期记忆到滚动窗口（Redis t:{tenant_id}:session:{thread_id}）。"""
        if app_state.redis is None:
            return
        key = f"t:{get_tenant_id()}:session:{thread_id}"
        await app_state.redis.rpush(key, _json(message))
        await app_state.redis.expire(key, SHORT_TTL_S)

    async def get_short(self, thread_id: str, limit: int = 20) -> List[Dict[str, Any]]:
        """读取最近 limit 条短期记忆。"""
        if app_state.redis is None:
            return []
        key = f"t:{get_tenant_id()}:session:{thread_id}"
        raw = await app_state.redis.lrange(key, -limit, -1)
        return [_loads(x) for x in raw]

    async def append_long(self, agent_id: str, block: str, content: str) -> None:
        """长期/语义记忆：写入 Milvus 向量存储（启动时由 MilvusManager 注入）。

        PG 落点（models.memory.AgentLongTermMemory 分页块）待接入；此处先保证语义检索可用，
        未就绪时降级为仅告警。
        """
        store = app_state.milvus_store
        if store is None:
            logger.warning("Milvus 未就绪，长期记忆降级为跳过写入")
            return
        from datetime import datetime

        await store.add_memory(
            id=f"{agent_id}:{block}:{datetime.now().timestamp()}",
            tenant_id=get_tenant_id() or "default",
            agent_id=agent_id,
            block=block,
            content=content,
            created_at=datetime.now().isoformat(timespec="seconds"),
        )

    async def stop(self) -> None:
        return None


def _json(obj: Any) -> str:
    import json

    return json.dumps(obj, ensure_ascii=False)


def _loads(s: str) -> Dict[str, Any]:
    import json

    return json.loads(s)
