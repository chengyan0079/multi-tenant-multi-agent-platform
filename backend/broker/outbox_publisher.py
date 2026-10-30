"""Outbox 投递协程：周期扫 agent_outbox(pending)，发往 MQ 并推进状态。

- 发成功 → mark_sent；
- 发失败 → inc_retry，超限 mark_failed（不再投递，留待排查）；
- 协程随 BrokerManager 启停（broker 未启用则不跑，Outbox 消息留存）。
"""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from backend.broker.envelope import TaskMessage
from backend.common.logger import logger
from backend.data.dao.ops.outbox_dao import OutboxDao

if TYPE_CHECKING:
    from backend.data.clients.broker import BrokerClient

# 投递节奏与上限（可按需调，见 docs §7）
PUBLISH_INTERVAL = 5  # 秒，扫表间隔
BATCH = 50  # 单次扫描上限
MAX_RETRIES = 3  # 投递重试上限（与消费重试共用阈值）


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
    oid = row["id"]
    p: dict = row["payload"]
    msg = TaskMessage(
        message_id=oid,
        type=p["type"],
        tenant_id=p.get("tenant_id"),
        user_id=p["user_id"],
        payload=p["payload"],
    )
    try:
        await client.publish(
            routing_key=row["topic"],
            body=msg.to_json(),
            message_id=oid,
            headers={"type": row["topic"]},
        )
        await OutboxDao.mark_sent(oid, row["retry_count"])
    except Exception as exc:  # noqa: BLE001
        rc = await OutboxDao.inc_retry(oid, str(exc))
        if rc >= MAX_RETRIES:
            await OutboxDao.mark_failed(oid, str(exc), rc)
            logger.error(f"Outbox 投递超限，标记 failed id={oid}：{exc}")
        else:
            logger.warning(f"Outbox 投递失败（将重试）id={oid}：{exc}")
