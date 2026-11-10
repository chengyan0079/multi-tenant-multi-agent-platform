"""RabbitMQ 异步客户端：连接与收发原语，消息持久+publisher confirm+独立 channel 消费。"""

from __future__ import annotations

from typing import Any, Awaitable, Callable
from uuid import uuid4

import aio_pika

from backend.common.logger import logger
from backend.data.clients.base import BaseClient, ClientError

# 消费回调：接收单条入站消息，自行 ack / nack
BrokerCallback = Callable[["aio_pika.IncomingMessage"], Awaitable[None]]


def _body_text(body: bytes) -> str:
    """消息体转可读 JSON 文本（非法 UTF-8 用替换字符兜底，不因日志干扰收发）。"""
    return bytes(body).decode("utf-8", errors="replace")


class BrokerClient(BaseClient):
    """RabbitMQ 异步客户端。"""

    name = "broker"

    def __init__(self, url: str, instance_id: str) -> None:
        self._url = url
        self._instance_id = instance_id
        self._conn: aio_pika.RobustConnection | None = None
        # 主 channel：声明拓扑与发布共用（发布已有 publisher confirm 保护）
        self._channel: aio_pika.Channel | None = None
        # 消费 channel：一队列一条，互不干扰彼此的 prefetch
        self._consumer_channels: list[aio_pika.Channel] = []

    @property
    def instance_id(self) -> str:
        """本进程实例标识，用于广播队列命名（每副本一条独占队列）。"""
        return self._instance_id

    @classmethod
    def from_settings(cls, cfg: "Any") -> "BrokerClient":
        """按配置构造（url 已含密码，见 BrokerSettings.url）。"""
        return cls(cfg.url, uuid4().hex[:12])

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
        for ch in self._consumer_channels:
            await _close_quietly(ch)
        self._consumer_channels.clear()
        if self._channel is not None:
            await _close_quietly(self._channel)
            self._channel = None
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    @property
    def raw(self) -> aio_pika.RobustConnection:
        if self._conn is None:
            raise ClientError("BrokerClient 未连接，请先 await connect()")
        return self._conn

    @property
    def channel(self) -> aio_pika.Channel:
        """主 channel，供拓扑声明使用。"""
        if self._channel is None:
            raise ClientError("BrokerClient 未连接，请先 await connect()")
        return self._channel

    async def health_check(self) -> bool:
        return self.is_connected

    # ---------- 能力 ----------
    async def publish(
        self,
        routing_key: str,
        body: bytes,
        *,
        message_id: str,
        exchange: str,
        headers: dict[str, Any] | None = None,
    ) -> None:
        """发布持久消息到指定 exchange。

        publisher confirm 模式下，publish 返回即代表 broker 已 ack。
        exchange 由调用方（routing.route）给出，本层不做业务判断。
        """
        ch = self.channel
        exchange_obj = await ch.get_exchange(exchange)
        msg = aio_pika.Message(
            body=body,
            message_id=message_id,
            headers=headers or {},
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,  # 持久消息，落盘
            content_type="application/json",
        )
        logger.debug(
            f"[mq] send exchange={exchange} routing_key={routing_key} "
            f"message_id={message_id} headers={headers or {}} body={_body_text(body)}"
        )
        await exchange_obj.publish(msg, routing_key=routing_key)

    async def consume(
        self,
        queue_name: str,
        *,
        prefetch: int,
        callback: BrokerCallback,
    ) -> None:
        """在独立 channel 上启动某队列的消费（手动 ack）。"""
        if self._conn is None:
            raise ClientError("BrokerClient 未连接，请先 await connect()")
        ch = await self._conn.channel()
        await ch.set_qos(prefetch_count=prefetch)
        self._consumer_channels.append(ch)
        queue = await ch.get_queue(queue_name)

        async def _on_message(message: "aio_pika.IncomingMessage") -> None:
            """统一记录收到的消息 JSON，再交给业务策略处理（ack/nack 仍由策略负责）。"""
            logger.debug(
                f"[mq] recv queue={queue_name} "
                f"routing_key={getattr(message, 'routing_key', None)} "
                f"message_id={getattr(message, 'message_id', None)} "
                f"body={_body_text(message.body)}"
            )
            await callback(message)

        await queue.consume(_on_message, no_ack=False)
        logger.info(f"RabbitMQ 开始消费队列 {queue_name}（prefetch={prefetch}）")


async def _close_quietly(channel: aio_pika.Channel) -> None:
    """关闭 channel；连接已断时关闭会报错，此处忽略以保证 close 幂等。"""
    try:
        if not channel.is_closed:
            await channel.close()
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"关闭 RabbitMQ channel 失败（忽略）：{exc}")
