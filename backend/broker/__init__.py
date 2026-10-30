"""消息队列 broker 包（RabbitMQ + aio-pika）。

对外导出常用入口；具体接入见 docs/消息队列对接设计（RabbitMQ+aio-pika）.md。
"""
from backend.broker.envelope import TaskMessage
from backend.broker.publish import publish_task

__all__ = ["TaskMessage", "publish_task"]
