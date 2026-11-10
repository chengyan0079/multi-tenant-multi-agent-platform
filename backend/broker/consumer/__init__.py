"""消费装配：按拓扑分组启动三组消费协程（业务 / 死信 / 广播）。"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Awaitable, Callable

from backend.broker.consumer.strategies import on_broadcast, on_dead_letter, on_task
from backend.broker.handlers import HANDLERS
from backend.broker.topology import (
    TASK_QUEUES,
    broadcast_queue_names,
    dlq_queue_names,
    validate_handler_coverage,
)
from backend.common.logger import logger

if TYPE_CHECKING:
    from aio_pika import IncomingMessage
    from backend.data.clients.broker import BrokerClient

Callback = Callable[["IncomingMessage"], Awaitable[None]]


async def start_consumers(client: "BrokerClient") -> list[asyncio.Task]:
    """启动全部消费协程。拓扑与 handler 不一致时抛错，阻断启动。"""
    validate_handler_coverage(HANDLERS.keys())

    tasks: list[asyncio.Task] = []
    for spec in TASK_QUEUES:
        tasks.append(_spawn(client, spec.name, spec.prefetch, on_task))
    for queue_name in dlq_queue_names():
        tasks.append(_spawn(client, queue_name, 1, on_dead_letter))
    for queue_name in broadcast_queue_names(client.instance_id):
        tasks.append(_spawn(client, queue_name, 1, on_broadcast))
    return tasks


def _spawn(
    client: "BrokerClient", queue_name: str, prefetch: int, callback: Callback
) -> asyncio.Task:
    task = asyncio.create_task(
        client.consume(queue_name, prefetch=prefetch, callback=callback),
        name=f"broker:{queue_name}",
    )
    task.add_done_callback(_report_exit)
    return task


def _report_exit(task: asyncio.Task) -> None:
    """消费协程异常退出时留下日志，避免协程静默消失。"""
    if task.cancelled():
        return
    if (exc := task.exception()) is not None:
        logger.error(f"消费协程异常退出 {task.get_name()}：{exc}")
