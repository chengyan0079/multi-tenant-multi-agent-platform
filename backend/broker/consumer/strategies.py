"""三类消费策略：业务任务/广播事件/最终死信，各负 ack/nack 边界；信封校验由 TaskMessage.from_json 统一。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.broker.envelope import MessageFormatError, TaskMessage
from backend.broker.handlers import HANDLERS
from backend.broker.topology import MAX_RETRIES
from backend.common.logger import logger
from backend.data.dao.ops.outbox_dao import DeadLetterDao, OutboxDao
from backend.observability.exception import BizException

if TYPE_CHECKING:
    from aio_pika import IncomingMessage


async def on_task(message: "IncomingMessage") -> None:
    """业务任务：信封校验 → 幂等判定 → handler → 成功 ack，失败走重试 / 死信。"""
    try:
        msg = TaskMessage.from_json(message.body)
    except MessageFormatError as exc:
        logger.exception(f"[task] 信封非法，丢弃：{exc}")
        await message.ack()
        return

    # 幂等：key 即 Outbox 主键。done / failed 都是终态，重投不再执行。
    # 如需人工重跑失败消息，应先把 outbox.status 重置为 pending（或换新 key）。
    if await OutboxDao.fetch_status(msg.key) in ("done", "failed"):
        await message.ack()
        return

    handler = HANDLERS.get(msg.type)
    if handler is None:
        logger.warning(f"[task] 无 handler 对应 type={msg.type}，丢弃")
        await message.ack()
        return

    try:
        await handler(msg)
        await OutboxDao.mark_done(msg.key, msg.header.retry_count)
        await message.ack()
    except BizException as exc:
        # 业务性失败（鉴权不足 / 参数非法）重试也不会变好，直接落 failed，避免白耗重试次数
        logger.exception(f"[task] 业务失败不重试 type={msg.type} key={msg.key}：{exc}")
        await OutboxDao.mark_failed(msg.key, str(exc), msg.header.retry_count)
        await message.ack()
    except Exception as exc:  # noqa: BLE001
        await _handle_failure(message, msg, exc)


async def _handle_failure(message: "IncomingMessage", msg: TaskMessage, exc: Exception) -> None:
    """失败处理：未超限 nack 进重试队列，超限落死信表后 ack。"""
    logger.exception(f"处理消息失败 type={msg.type} key={msg.key}：{exc}")
    retry_count = await OutboxDao.inc_retry(msg.key, str(exc))
    if retry_count < MAX_RETRIES:
        await message.nack(requeue=False)  # 进 RETRY_DLX，TTL 后回原队列
        return

    await DeadLetterDao.write(
        topic=msg.type.value,
        payload=message.body,
        origin_queue=msg.type.value,
        error=str(exc),
        retry_count=retry_count,
        tenant_id=msg.header.tenant_id,
    )
    await OutboxDao.mark_failed(msg.key, str(exc), retry_count)
    await message.ack()


async def on_broadcast(message: "IncomingMessage") -> None:
    """广播事件：每个副本各自处理，不幂等、不重试，失败也不阻塞。"""
    try:
        msg = TaskMessage.from_json(message.body)
    except MessageFormatError as exc:
        logger.exception(f"[broadcast] 信封非法，丢弃：{exc}")
        await message.ack()
        return

    handler = HANDLERS.get(msg.type)
    if handler is None:
        logger.warning(f"[broadcast] 无 handler 对应 type={msg.type}，丢弃")
        await message.ack()
        return

    try:
        await handler(msg)
    except Exception as exc:  # noqa: BLE001
        logger.exception(f"[broadcast] 处理失败 type={msg.type}：{exc}")
    await message.ack()


async def on_dead_letter(message: "IncomingMessage") -> None:
    """最终死信：仅告警。业务侧超限时已落 agent_dead_letter 表。"""
    try:
        logger.warning(f"[dlq] 收到死信消息 body={message.body[:200]!r}")
    finally:
        await message.ack()
