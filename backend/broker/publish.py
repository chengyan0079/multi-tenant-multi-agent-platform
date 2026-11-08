"""任务入队：业务代码唯一的发消息入口。

本模块只写 agent_outbox(pending) 就返回，真正投递由 OutboxPublisher 协程异步完成；
broker 未启用时消息留在 Outbox，启用后补发，调用方无需关心连接状态。
消息走哪个交换机由 routing.route() 按 type 决定，调用方不需要也不应该指定。
"""
from __future__ import annotations

import uuid6

from backend.broker.envelope import MessageHeader, TaskMessage
from backend.broker.routing import route
from backend.broker.types import TaskType
from backend.common.logger import logger, trace_id_ctx
from backend.data.dao.ops.outbox_dao import OutboxDao
from backend.services.config_refresh import publish as publish_config_refresh_signal


async def enqueue_task(
    type: TaskType,
    *,
    tenant_id: int | None,
    user_id: int,
    data: dict,
    key: str | None = None,
    trace_id: str | None = None,
) -> str | None:
    """写入一条待投递任务，返回消息 key（同时是 Outbox 主键）。

    key 缺省由 uuid7 生成，作为消息幂等键：消费端按它去重，重投不会重复生效。
    返回 None 表示写 Outbox 失败，调用方据此判断是否需要提示重试。
    """
    msg_key = key or str(uuid6.uuid7())
    header = MessageHeader(
        tenant_id=tenant_id,
        user_id=user_id,
        # 请求线程里自动带上当前 trace_id，后台任务没有则为 None
        trace_id=trace_id or trace_id_ctx.get(),
    )
    msg = TaskMessage(key=msg_key, type=type, header=header, data=data)
    try:
        outbox_id = await OutboxDao.enqueue(
            message_id=msg_key,
            topic=type.value,
            payload=msg.to_dict(),
            tenant_id=tenant_id,
            message_kind=route(type).kind.value,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(f"写 Outbox 失败 type={type} tenant={tenant_id}：{exc}")
        return None
    logger.debug(f"[outbox] enqueue {type} key={outbox_id}")
    return str(outbox_id)


async def publish_config_refresh(*targets: str) -> None:
    """发布配置变更信号到 Redis，供其它副本定时拉取后刷新内存注册表。

    注意：这是跨副本缓存失效信号，不属于 Outbox 消息，故不写 agent_outbox、不走 MQ。
    保留本函数是为了让 5 个管理端调用点无需改动。
    """
    await publish_config_refresh_signal(*targets)
