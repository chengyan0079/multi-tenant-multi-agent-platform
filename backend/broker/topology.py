"""消息队列拓扑：交换机、队列、重试与死信链路的唯一定义处。

新增一类异步任务只需两步：在 TaskType 加枚举值、在 TASK_QUEUES 加一行 QueueSpec，
并补对应 handler。声明、重试链路、死信队列、消费装配都由此推导，启动期做一致性对账。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Container

import aio_pika

from backend.broker.types import TaskType
from backend.common.logger import logger

if TYPE_CHECKING:
    from backend.data.clients.broker import BrokerClient

# 业务交换机：routing_key 与队列名一一对应（保留 topic 语义，便于将来按前缀分流）
EXCHANGE = "agent.platform"
RETRY_DLX = "agent.platform.retry"
FINAL_DLX = "agent.platform.dlx"
# 广播交换机：配置刷新等全副本事件
BROADCAST_EXCHANGE = "agent.platform.broadcast"

RETRY_TTL_MS = 30000  # 重试延迟（毫秒）
MAX_RETRIES = 3  # 重试上限（投递与消费共用），超出落死信表


@dataclass(frozen=True)
class QueueSpec:
    """一个业务队列的声明。队列名取枚举值。"""

    type: TaskType
    exchange: str = EXCHANGE
    retry: bool = True
    # 每队列独立 channel，prefetch 就是该队列的并发度：长任务给 1，短任务给大一些
    prefetch: int = 1

    @property
    def name(self) -> str:
        """队列名，同时是 routing_key。"""
        return self.type.value


TASK_QUEUES: tuple[QueueSpec, ...] = (
    QueueSpec(TaskType.AGENT_RUN, prefetch=1),  # 多 Agent 串联 / 长推理
    QueueSpec(TaskType.QA_PARSE, prefetch=2),  # qa 知识库文档解析 + 向量化，吃 CPU
    QueueSpec(TaskType.RESUME_REVIEW, prefetch=1),  # 简历评审跑 LangGraph
    QueueSpec(TaskType.QA_RAGAS_REVIEW, prefetch=1),  # 问答 RAGAS 质量测评（LLM 打分）
    QueueSpec(TaskType.EXAM_REVIEW, prefetch=1),  # 试卷批改跑 LangGraph（含 HITL 暂停）
    QueueSpec(TaskType.NOTIFY_SEND, prefetch=10),  # 通知外发，IO 等待为主
    QueueSpec(TaskType.AUDIT_FLUSH, prefetch=20),  # 审计批量落库，单条很快
)

# 广播类型：每个副本各消费一份（FANOUT + 独占队列），不参与重试 / 死信。
# 当前无业务使用（配置刷新已改用 Redis 版本号拉取）；保留拓扑代码供将来真正的广播场景。
BROADCAST_TYPES: tuple[TaskType, ...] = ()


def retry_queue_name(queue_name: str) -> str:
    return f"{queue_name}.retry"


def dlq_queue_name(queue_name: str) -> str:
    return f"{queue_name}.dlq"


def dlq_queue_names() -> tuple[str, ...]:
    return tuple(dlq_queue_name(spec.name) for spec in TASK_QUEUES if spec.retry)


def broadcast_queue_name(task_type: TaskType, instance_id: str) -> str:
    return f"{task_type.value}.{instance_id}"


def broadcast_queue_names(instance_id: str) -> tuple[str, ...]:
    return tuple(broadcast_queue_name(t, instance_id) for t in BROADCAST_TYPES)


def validate_handler_coverage(handler_types: Container[TaskType]) -> None:
    """启动期对账：声明的队列 / 广播类型必须与已注册 handler 完全一致。

    缺 handler 会让消息进来后被静默丢弃，孤儿 handler 则永远不会被调用，
    两类都是配置错误，直接让启动失败。
    """
    declared = {spec.type for spec in TASK_QUEUES} | set(BROADCAST_TYPES)
    registered = set(handler_types)
    if declared != registered:
        missing = sorted(str(t) for t in declared - registered)
        orphan = sorted(str(t) for t in registered - declared)
        raise RuntimeError(
            f"broker 拓扑与 handler 不一致：缺 handler={missing}，无对应队列={orphan}"
        )


async def declare_all(client: "BrokerClient") -> None:
    """声明全部交换机与队列。幂等可重入。

    注意：队列已存在时 RabbitMQ 会校验 durable / arguments 是否一致，
    调整 QueueSpec 或 TTL 后需先删除旧队列再启动。
    """
    ch = client.channel
    await ch.declare_exchange(EXCHANGE, aio_pika.ExchangeType.TOPIC, durable=True)
    await ch.declare_exchange(RETRY_DLX, aio_pika.ExchangeType.TOPIC, durable=True)
    await ch.declare_exchange(FINAL_DLX, aio_pika.ExchangeType.TOPIC, durable=True)
    await ch.declare_exchange(
        BROADCAST_EXCHANGE, aio_pika.ExchangeType.FANOUT, durable=True
    )

    for spec in TASK_QUEUES:
        await _declare_task_queue(ch, spec)
    for task_type in BROADCAST_TYPES:
        await _declare_broadcast_queue(
            ch, broadcast_queue_name(task_type, client.instance_id)
        )
    logger.info(
        f"RabbitMQ 拓扑已声明：{len(TASK_QUEUES)} 个业务队列，"
        f"{len(BROADCAST_TYPES)} 个广播类型"
    )


async def _declare_task_queue(ch: "aio_pika.Channel", spec: QueueSpec) -> None:
    """声明业务队列，以及它的重试队列与最终死信队列。"""
    dlx_args = (
        {
            "x-dead-letter-exchange": RETRY_DLX,
            "x-dead-letter-routing-key": spec.name,
        }
        if spec.retry
        else {}
    )
    queue = await ch.declare_queue(spec.name, durable=True, arguments=dlx_args)
    await queue.bind(spec.exchange, routing_key=spec.name)
    if not spec.retry:
        return

    # 重试队列：TTL 到期后经 FINAL_DLX 按队列名路由回原队列
    retry_q = await ch.declare_queue(
        retry_queue_name(spec.name),
        durable=True,
        arguments={
            "x-message-ttl": RETRY_TTL_MS,
            "x-dead-letter-exchange": FINAL_DLX,
            "x-dead-letter-routing-key": spec.name,
        },
    )
    await retry_q.bind(RETRY_DLX, routing_key=spec.name)

    # 最终死信：消费端超限后落库并 ack，此队列仅作兜底通道
    dlq_q = await ch.declare_queue(dlq_queue_name(spec.name), durable=True)
    await dlq_q.bind(FINAL_DLX, routing_key=spec.name)


async def _declare_broadcast_queue(ch: "aio_pika.Channel", queue_name: str) -> None:
    """独占 + 自动删除：实例下线后队列消失，不积压无人消费的广播消息。"""
    queue = await ch.declare_queue(queue_name, exclusive=True, auto_delete=True)
    await queue.bind(BROADCAST_EXCHANGE)
