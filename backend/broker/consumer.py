"""消费循环：接收消息 → 幂等判定 → 路由 handler → 手动 ack / 重试 / 死信。

流程（见 docs/消息队列对接设计 §6.2 / §6.3 / §7）：
1. 解析 TaskMessage；解析失败直接 ack 丢弃（毒消息不阻塞队列）；
2. 无对应 handler → ack 丢弃并告警；
3. 幂等：outbox 已 done → ack 跳过（at-least-once 重投 / 死信重试不重复生效）；
4. 调 handler（内部 authorize_task 做租户 / scope 鉴权）；
5. 成功 → mark_done + ack；
6. 异常 → inc_retry，超 MAX 落死信表 + mark_failed + ack（已落表，不进队列），
   未超限 → nack(requeue=False) 进 RETRY_DLX → .retry 队列（TTL）→ 回原队列重投。
"""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from backend.broker.dlq import QUEUES, DLQ_QUEUES, MAX_RETRIES
from backend.broker.envelope import TaskMessage
from backend.broker.handlers import HANDLERS
from backend.common.logger import logger
from backend.data.dao.ops.outbox_dao import DeadLetterDao, OutboxDao

if TYPE_CHECKING:
    from aio_pika import IncomingMessage
    from backend.data.clients.broker import BrokerClient


async def _on_message(message: "IncomingMessage") -> None:
    msg: TaskMessage | None = None
    try:
        msg = TaskMessage.from_json(message.body)
        oid = msg.message_id
        # 幂等：已 done 直接跳过（重投 / 死信重试不重复生效，见 §6.3）
        if oid:
            if await OutboxDao.fetch_status(oid) == "done":
                await message.ack()
                return
        handler = HANDLERS.get(msg.type)
        if handler is None:
            logger.warning(f"无 handler 对应 type={msg.type}，丢弃")
            await message.ack()
            return
        await handler(msg)
        if oid:
            await OutboxDao.mark_done(oid, msg.retry_count)
        await message.ack()
    except Exception as exc:  # noqa: BLE001
        mtype = msg.type if msg is not None else "?"
        logger.exception(f"处理消息失败 type={mtype}：{exc}")
        oid = msg.message_id if msg is not None else None
        tenant_id = msg.tenant_id if msg is not None else None
        if oid:
            rc = await OutboxDao.inc_retry(oid, str(exc))
            if rc >= MAX_RETRIES:
                # 超限：落死信表 + 标 failed + ack（已落表，不进队列）
                await DeadLetterDao.write(
                    topic=mtype,
                    payload=message.body,
                    origin_queue=mtype,
                    error=str(exc),
                    retry_count=rc,
                    tenant_id=tenant_id,
                )
                await OutboxDao.mark_failed(oid, str(exc), rc)
                await message.ack()
                return
        # 未超限：nack 进 RETRY_DLX → .retry 队列（TTL）→ 回原队列重投
        await message.nack(requeue=False)


async def _on_dlq(message: "IncomingMessage") -> None:
    """最终死信队列消费：仅记录告警（主要落表已在业务消费端完成）。"""
    try:
        logger.warning(f"[dlq] 收到死信消息 body={message.body[:200]!r}")
    finally:
        await message.ack()


async def start_consumers(client: "BrokerClient") -> list[asyncio.Task]:
    """启动业务队列 + 死信队列消费协程。"""
    tasks: list[asyncio.Task] = []
    for queue_name in QUEUES:
        tasks.append(asyncio.create_task(_consume_queue(client, queue_name, _on_message)))
    for queue_name in DLQ_QUEUES:
        tasks.append(asyncio.create_task(_consume_queue(client, queue_name, _on_dlq)))
    return tasks


async def _consume_queue(client: "BrokerClient", queue_name: str, callback) -> None:
    await client.consume(queue_name, callback)
