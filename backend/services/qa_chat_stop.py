"""QA 流式回答的停止标记（Redis，跨 worker 生效）。

参考 RAG-Ultra：
- `POST /qa/chat/stop` 写入短 TTL 标记；
- 流式生成器在产出事件前检查标记，命中则停止；
- 进入/结束时清理，避免残留误停。
"""
from __future__ import annotations

from backend.app_state import app_state
from backend.common.logger import logger

# 停止标记 TTL：足够覆盖一次流式生成，过期自动清理
_STOP_TTL_S = 60


def _key(tenant_id: int, user_id: int, session_id: str) -> str:
    return f"qa:chatstop:{tenant_id}:{user_id}:{session_id}"


async def set_chat_stop(tenant_id: int, user_id: int, session_id: str) -> None:
    """置停止标记（幂等）。"""
    redis = app_state.redis
    if redis is None:
        return
    try:
        await redis.set(_key(tenant_id, user_id, session_id), "1", ex=_STOP_TTL_S)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"qa_chat_stop.set_failed | session={session_id} | {exc}")


async def is_chat_stopped(tenant_id: int, user_id: int, session_id: str) -> bool:
    """是否已请求停止；Redis 不可用时返回 False（不阻断生成）。"""
    redis = app_state.redis
    if redis is None:
        return False
    try:
        return bool(await redis.get(_key(tenant_id, user_id, session_id)))
    except Exception:
        return False


async def clear_chat_stop(tenant_id: int, user_id: int, session_id: str) -> None:
    """清除停止标记（开始/结束时调用）。"""
    redis = app_state.redis
    if redis is None:
        return
    try:
        await redis.delete(_key(tenant_id, user_id, session_id))
    except Exception:
        pass
