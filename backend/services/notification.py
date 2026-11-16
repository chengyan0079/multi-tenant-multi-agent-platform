"""通知外发：按渠道分发，渠道以注册表方式扩展。"""

from __future__ import annotations

from typing import Any, Protocol

from backend.common.logger import logger


class NotifyChannel(Protocol):
    """通知渠道契约。"""

    name: str

    async def send(
        self,
        *,
        tenant_id: int | None,
        user_id: int,
        content: str,
        **extra: Any,
    ) -> None:
        """发送一条通知；失败直接抛异常，由消费端重试。"""
        ...


# 渠道注册表：默认空；实现 email / wecom / webhook / ticket 后注册于此（见 docs/后端TODO清单.md）
CHANNELS: dict[str, NotifyChannel] = {}


async def send_notification(
    *,
    channel: str | None,
    tenant_id: int | None,
    user_id: int,
    content: str,
    **extra: Any,
) -> None:
    """按渠道外发通知；渠道未注册时记录告警并跳过，不阻塞其它任务。"""
    impl = CHANNELS.get(channel or "")
    if impl is None:
        logger.warning(
            f"[notify] 渠道未注册 channel={channel} tenant={tenant_id} 已注册={sorted(CHANNELS)}"
        )
        return
    await impl.send(tenant_id=tenant_id, user_id=user_id, content=content, **extra)
