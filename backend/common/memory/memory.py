"""
memory - 分层记忆抽象（设计文档 §6.1）

短期 Redis 滚动窗口 / 长期 PG Letta 式分页 / 语义 Milvus。本文件定义统一接口与基于 Redis 的
短期记忆实现，长期与语义落点后续接 models + milvus_store。单 Agent 直接复用，无需自建。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from backend.app_state import app_state, get_tenant_id, get_user_id
from backend.common.logger import get_logger

logger = get_logger("memory")

SHORT_TTL_S = 60 * 60 * 24  # 短期会话窗口保留 1 天


def _session_key(thread_id: str) -> str | None:
    """短期记忆 key：租户 → 用户 → 会话三段。

    任一段缺失就返回 None 由调用方跳过：宁可本次不记忆，也不能让不同用户
    落到同一个 key 上读到对方的上下文。
    """
    tenant_id = get_tenant_id()
    user_id = get_user_id()
    if tenant_id is None or user_id is None:
        return None
    return f"t:{tenant_id}:u:{user_id}:session:{thread_id}"


class MemoryStore:
    """记忆存储：短期（Redis）+ 长期/语义（后续接 PG/Milvus）。"""

    async def start(self) -> None:
        # 资源由 RedisManager / PostgresManager / MilvusManager 注入 app_state，此处仅做可用性检查
        if app_state.redis is None:
            logger.warning("Redis 未就绪，短期记忆降级为无操作")

    async def push_short(self, thread_id: str, message: Dict[str, Any]) -> None:
        """追加一条短期记忆到滚动窗口（Redis t:{tenant}:u:{user}:session:{thread}）。"""
        if app_state.redis is None:
            return
        key = _session_key(thread_id)
        if key is None:
            logger.warning("缺少租户或用户上下文，跳过短期记忆写入（避免跨用户共享）")
            return
        await app_state.redis.rpush(key, _json(message))
        await app_state.redis.expire(key, SHORT_TTL_S)

    async def get_short(self, thread_id: str, limit: int = 20) -> List[Dict[str, Any]]:
        """读取最近 limit 条短期记忆。"""
        if app_state.redis is None:
            return []
        key = _session_key(thread_id)
        if key is None:
            logger.warning("缺少租户或用户上下文，跳过短期记忆读取（避免跨用户共享）")
            return []
        raw = await app_state.redis.lrange(key, -limit, -1)
        return [_loads(x) for x in raw]

    async def append_long(self, agent_id: str, block: str, content: str) -> None:
        """长期/语义记忆：写入 Milvus 向量存储（启动时由 MilvusManager 注入）。

        长期记忆按「租户 + 用户 + 智能体」归属，检索侧同条件过滤；身份缺失不写，
        否则记忆会被写成租户共享。PG 落点（AgentLongTermMemory 分页块）待接入。
        """
        store = app_state.milvus_store
        if store is None:
            logger.warning("Milvus 未就绪，长期记忆降级为跳过写入")
            return
        tenant_id = get_tenant_id()
        user_id = get_user_id()
        if tenant_id is None or user_id is None:
            logger.warning("缺少租户或用户上下文，跳过长期记忆写入（避免跨用户共享）")
            return
        from datetime import datetime

        await store.add_memory(
            id=f"{tenant_id}:{user_id}:{agent_id}:{block}:{datetime.now().timestamp()}",
            tenant_id=str(tenant_id),
            user_id=str(user_id),
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
