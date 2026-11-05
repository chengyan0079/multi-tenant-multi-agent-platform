"""消息队列 broker 包（RabbitMQ + aio-pika）。

对外只暴露三样东西：消息信封、入队入口、配置广播入口。
拓扑与路由细节见 topology / routing，具体接入见 docs/消息队列对接设计（RabbitMQ+aio-pika）.md。
"""
from backend.broker.envelope import TaskMessage
from backend.broker.publish import enqueue_task, publish_config_refresh

__all__ = ["TaskMessage", "enqueue_task", "publish_config_refresh"]
