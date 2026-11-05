"""BrokerManager（order=20）：建立 RabbitMQ 连接、声明基础设施、启动消费协程。

启用由 BrokerSettings.enabled 控制（默认 False）：未启用则不注册、不连接，
避免无 broker 时阻断整个服务启动（AppServer fail-fast 回滚）。broker 是独立中间件，
与其它基础设施（Redis / PG）无依赖，故放同一阶段并行。
"""
from __future__ import annotations

import asyncio
from typing import Optional

from backend.app_state import app_state
from backend.broker.outbox_publisher import run_publisher
from backend.broker.topology import declare_all
from backend.common.logger import logger
from backend.data.clients.broker import BrokerClient
from backend.server.base_manager import BaseManager, HealthInfo


class BrokerManager(BaseManager):
    def __init__(self) -> None:
        super().__init__("broker")
        self._tasks: list[asyncio.Task] = []

    async def start(self) -> None:
        if not app_state.settings.broker.enabled:
            logger.info("RabbitMQ 未启用（RABBITMQ_ENABLED=false），跳过")
            return
        # 连接由 ClientBundle 显式持有，stop 时统一释放
        client = app_state.clients.ensure(
            "broker", lambda: BrokerClient.from_settings(app_state.settings.broker)
        )
        await client.connect()
        app_state.broker = client
        await declare_all(client)
        # 业务队列 + 死信队列 + 广播队列消费协程（拓扑见 broker/topology.py）
        self._tasks = await self._start_consumers(client)
        # Outbox 投递协程：扫 agent_outbox(pending) 异步发 MQ（见 §6.4）
        self._stop = asyncio.Event()
        self._tasks.append(asyncio.create_task(run_publisher(client, self._stop)))
        logger.info("RabbitMQ 消费者与 Outbox 投递协程已启动")

    async def stop(self) -> None:
        if getattr(self, "_stop", None) is not None:
            self._stop.set()
        for t in self._tasks:
            t.cancel()
        self._tasks.clear()
        if app_state.clients.has("broker"):
            await app_state.clients.get_as("broker", BrokerClient).close()
        app_state.broker = None

    async def health(self) -> HealthInfo:
        client = app_state.broker
        if client is None:
            return HealthInfo(status="stopped", detail="未启用")
        try:
            ok = await client.health_check()
            return HealthInfo(status="running" if ok else "down")
        except Exception as exc:  # noqa: BLE001
            return HealthInfo(status="down", detail=f"{type(exc).__name__}: {exc}")

    @staticmethod
    async def _start_consumers(client: BrokerClient) -> list[asyncio.Task]:
        from backend.broker.consumer import start_consumers

        return await start_consumers(client)
