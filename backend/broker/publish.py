"""任务发布 helper：业务代码调用，落 Outbox（本地消息表）后即返回。

统一走 Outbox（见 docs/消息队列对接设计 §6.4）：本函数只写 agent_outbox(pending)，
真正的 MQ 投递由 BrokerManager 内的 OutboxPublisher 协程异步完成。broker 未启用时
消息留在 Outbox，启用后由投递协程补发（不丢），调用方无需关心 broker 连接状态。

routing_key 即消息 type（与 broker/dlq.py 的 QUEUES 同名）。
"""
from __future__ import annotations

import uuid6

from backend.broker.envelope import TaskMessage
from backend.data.dao.ops.outbox_dao import OutboxDao
from backend.common.logger import logger


async def publish_task(
    routing_key: str,
    *,
    type: str,
    tenant_id: int | None,
    user_id: int,
    payload: dict,
) -> str | None:
    """发布一条任务：写 Outbox(pending) 并返回 outbox id（即后续 MQ message_id）。

    routing_key 当前等同于 type；保留参数以兼容调用方。
    """
    msg = TaskMessage(
        type=type,
        tenant_id=tenant_id,
        user_id=user_id,
        payload=payload,
        message_id=uuid6.uuid7().hex,
    )
    try:
        outbox_id = await OutboxDao.enqueue(
            topic=type, payload=msg.to_dict(), tenant_id=tenant_id
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(f"写 Outbox 失败 type={type} tenant={tenant_id}：{exc}")
        return None
    logger.debug(f"[outbox] enqueue {type} id={outbox_id}")
    return outbox_id
