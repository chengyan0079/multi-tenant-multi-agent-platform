"""配置变更广播 handler：各副本收到后刷新本地内存注册表。"""
from __future__ import annotations

from backend.app_state import app_state
from backend.broker.envelope import TaskMessage
from backend.broker.security import authorize_task
from backend.common.logger import logger
from backend.server.managers.model_manager import ModelManager
from backend.server.managers.plugin_manager import reload_plugins

_seen_ts = 0.0


async def handle_config_refresh(msg: TaskMessage) -> None:
    global _seen_ts

    await authorize_task(msg.header.user_id, msg.header.tenant_id, [])

    # 多副本各自扫 Outbox 会重复投递，按时间戳丢弃旧消息
    ts = float(msg.data.get("ts") or 0)
    if ts and ts <= _seen_ts:
        return
    if ts:
        _seen_ts = ts

    targets = msg.data.get("targets") or []
    if "plugin_registry" in targets:
        await reload_plugins()
    if "llm_factory" in targets:
        await ModelManager().reload()
    if "agent_registry" in targets:
        registry = app_state.agent_registry
        if registry is not None:
            await registry.refresh()
    logger.info(f"[config.refresh] targets={targets} ts={ts}")
