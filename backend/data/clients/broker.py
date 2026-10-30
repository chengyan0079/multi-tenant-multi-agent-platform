"""RabbitMQ 异步客户端（aio-pika）。

封装连接、声明基础设施（exchange / queue / DLX，均 durable）、发布（持久消息 +
publisher confirm）、消费（手动 ack）。连接由 `connect_robust` 管理，断线自动重连。

设计要点（见 docs/消息队列对接设计 §6）：
- 队列 / 交换器 durable=True，消息 delivery_mode=PERSISTENT → broker 重启不丢；
- publisher confirm 保证"发出去被 broker 接收"，防静默丢失；
- 消费 no_ack=False + prefetch_count=1 → 手动 ack、公平分发。
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable

import aio_pika

from backend.common.logger import logger
from backend.data.clients.base import BaseClient, ClientError
from backend.broker.dlq import (
    EXCHANGE,
    QUEUES,
    RETRY_DLX,
    FINAL_DLX,
    RETRY_TTL_MS,
)

# 消费回调：接收单条入站消息，自行 ack / nack
BrokerCallback = Callable[["aio_pika.IncomingMessage"], Awaitable[None]]


class BrokerClient(BaseClient):
    """RabbitMQ 异步客户端。"""

    name = "broker"

    def __init__(self, url: str) -> None:
        self._url = url
        self._conn: aio_pika.RobustConnection | None = None
        self._channel: aio_pika.Channel | None = None

    @classmethod
    def from_settings(cls, cfg: "Any") -> "BrokerClient":
        """按配置构造（url 已含密码，见 BrokerSettings.url）。"""
        return cls(cfg.url)

    # ---------- 生命周期 ----------
    @property
    def is_connected(self) -> bool:
        return self._conn is not None and not self._conn.is_closed

    async def connect(self) -> None:
        if self._conn is not None:
            return
        # connect_robust：断线自动重连
        self._conn = await aio_pika.connect_robust(self._url)
        self._channel = await self._conn.channel()
        # 开启 publisher confirm：publish 会等待 broker ack，防静默丢失。
        # aio-pika 9 用 channel.declare_confirm()；10+ 的 RobustChannel 默认已开启，
        # 此处兼容两种版本（无该方法则跳过，robust 连接下 publish 仍等 ack）。
        declare_confirm = getattr(self._channel, "declare_confirm", None)
        if declare_confirm is not None:
            await declare_confirm()
        logger.info("RabbitMQ 连接就绪")

    async def close(self) -> None:
        if self._channel is not None:
            await self._channel.close()
            self._channel = None
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    @property
    def raw(self) -> aio_pika.RobustConnection:
        if self._conn is None:
            raise ClientError("BrokerClient 未连接，请先 await connect()")
        return self._conn

    async def health_check(self) -> bool:
        return self.is_connected

    # ---------- 能力 ----------
    async def declare_infra(self) -> None:
        """声明 exchange / 重试与最终死信 exchange / 业务队列 + 重试队列 + 死信队列。幂等可重入。"""
        ch = self._channel
        assert ch is not None, "connect() 未完成"
        await ch.declare_exchange(EXCHANGE, aio_pika.ExchangeType.TOPIC, durable=True)
        await ch.declare_exchange(RETRY_DLX, aio_pika.ExchangeType.TOPIC, durable=True)
        await ch.declare_exchange(FINAL_DLX, aio_pika.ExchangeType.TOPIC, durable=True)
        for queue_name in QUEUES:
            # 业务队列：失败 nack 进 RETRY_DLX（按队列名路由到 .retry 队列）
            queue = await ch.declare_queue(
                queue_name,
                durable=True,
                arguments={
                    "x-dead-letter-exchange": RETRY_DLX,
                    "x-dead-letter-routing-key": queue_name,
                },
            )
            await queue.bind(EXCHANGE, routing_key=queue_name)
            # 重试队列：TTL 后回 FINAL_DLX（按队列名路由回原队列重投）
            retry_q = await ch.declare_queue(
                f"{queue_name}.retry",
                durable=True,
                arguments={
                    "x-message-ttl": RETRY_TTL_MS,
                    "x-dead-letter-exchange": FINAL_DLX,
                    "x-dead-letter-routing-key": queue_name,
                },
            )
            await retry_q.bind(RETRY_DLX, routing_key=queue_name)
            # 最终死信队列：绑定 FINAL_DLX，routing_key=队列名（预留通道，消费端落表后不再入队）
            dlq_q = await ch.declare_queue(f"{queue_name}.dlq", durable=True)
            await dlq_q.bind(FINAL_DLX, routing_key=queue_name)

    async def publish(
        self,
        routing_key: str,
        body: bytes,
        *,
        message_id: str,
        headers: dict[str, Any] | None = None,
        exchange: str = EXCHANGE,
    ) -> None:
        """发布持久消息到指定 exchange（topic）。需先 declare_infra。

        publisher confirm 模式下，publish 返回即代表 broker 已 ack。
        exchange 默认业务 EXCHANGE；重试超限时消费端用 FINAL_DLX 转存死信。
        """
        ch = self._channel
        assert ch is not None, "connect() 未完成"
        exchange_obj = await ch.get_exchange(exchange)
        msg = aio_pika.Message(
            body=body,
            message_id=message_id,
            headers=headers or {},
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,  # 持久消息，落盘
            content_type="application/json",
        )
        await exchange_obj.publish(msg, routing_key=routing_key)

    async def consume(self, queue_name: str, callback: BrokerCallback) -> None:
        """启动某队列的消费（手动 ack，prefetch=1）。"""
        ch = self._channel
        assert ch is not None, "connect() 未完成"
        await ch.set_qos(prefetch_count=1)  # 公平分发，避免单 worker 积压
        queue = await ch.get_queue(queue_name)
        await queue.consume(callback, no_ack=False)  # 手动 ack
        logger.info(f"RabbitMQ 开始消费队列 {queue_name}")
