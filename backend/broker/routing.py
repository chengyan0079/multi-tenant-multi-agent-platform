"""消息路由：消息类型 → 投递目标的唯一判定处。

业务消息与广播消息的区分只在这里做，投递端（outbox）与消费端都读同一份结果，
避免同一条规则散落在声明、投递、消费各处。
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from backend.broker.topology import BROADCAST_EXCHANGE, BROADCAST_TYPES, EXCHANGE
from backend.broker.types import TaskType


class Kind(str, Enum):
    """消费方式。"""

    TASK = "task"  # 竞争消费：幂等 + 重试 + 死信
    BROADCAST = "broadcast"  # 每副本各收一份：不幂等、不重试


@dataclass(frozen=True)
class Route:
    """一条消息的投递目标。"""

    exchange: str
    routing_key: str
    kind: Kind


def route(task_type: TaskType) -> Route:
    """按类型决定投递目标。"""
    if task_type in BROADCAST_TYPES:
        return Route(BROADCAST_EXCHANGE, task_type.value, Kind.BROADCAST)
    return Route(EXCHANGE, task_type.value, Kind.TASK)
