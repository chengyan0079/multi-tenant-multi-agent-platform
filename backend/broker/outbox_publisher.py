"""Outbox 投递协程：周期扫描 pending 发往 MQ 并推进状态，信封非法/超限置 failed。"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from backend.broker.envelope import MessageFormatError, TaskMessage
from backend.broker.routing import route
from backend.broker.topology import MAX_RETRIES
from backend.common.logger import logger
from backend.data.dao.ops.outbox_dao import OutboxDao

if TYPE_CHECKING:
    from backend.data.clients.broker import BrokerClient

# 投递节奏（可按需调，见 docs §7）；重试上限与消费端共用 topology.MAX_RETRIES
PUBLISH_INTERVAL = 5  # 秒，扫表间隔
BATCH = 50  # 单次扫描上限


async def run_publisher(client: "BrokerClient", stop_event: asyncio.Event) -> None:
    """投递主循环：直到 stop_event 置位。"""
    logger.info("Outbox 投递协程已启动")
    while not stop_event.is_set():
        try:
            rows = await OutboxDao.fetch_pending(BATCH)
            for row in rows:
                await _publish_one(client, row)
        except asyncio.CancelledError:  # 协程被取消，干净退出
            break
        except Exception as exc:  # noqa: BLE001
            logger.exception(f"Outbox 投递协程异常：{exc}")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=PUBLISH_INTERVAL)
        except asyncio.TimeoutError:
            continue
    logger.info("Outbox 投递协程已退出")


async def _publish_one(client: "BrokerClient", row: dict) -> None:
    oid = str(row["id"])  # asyncpg 返回 UUID 对象，统一成字符串
    try:
        msg = TaskMessage.from_dict(row["payload"])
    except MessageFormatError as exc:
        # 信封本身坏了，重试也不会变好，直接置 failed 留待排查
        await OutboxDao.mark_failed(oid, f"信封非法：{exc}", row["retry_count"])
        logger.exception(f"Outbox 信封非法，标记 failed key={oid}：{exc}")
        return

    target = route(msg.type)
    try:
        await client.publish(
            routing_key=target.routing_key,
            body=msg.to_json(),
            message_id=msg.key,
            headers={"type": msg.type.value},
            exchange=target.exchange,
        )
        await OutboxDao.mark_sent(oid, row["retry_count"])
    except Exception as exc:  # noqa: BLE001
        retry_count = await OutboxDao.inc_retry(oid, str(exc))
        if retry_count >= MAX_RETRIES:
            await OutboxDao.mark_failed(oid, str(exc), retry_count)
            logger.exception(f"Outbox 投递超限，标记 failed key={oid}：{exc}")
        else:
            logger.exception(f"Outbox 投递失败（将重试）key={oid}：{exc}")
