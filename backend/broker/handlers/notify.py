"""通知外发 handler（HITL 确认后外发动作）。

本轮落鉴权与消息结构；具体渠道（邮件 / 企微 / Webhook / 工单）接 TODO，
失败走重试 + 死信（见文档 §7）。
"""
from __future__ import annotations

from backend.broker.envelope import TaskMessage
from backend.broker.security import authorize_task
from backend.common.logger import logger


async def handle_notify_send(msg: TaskMessage) -> None:
    # 通知由具 RBAC 权限者（超管 / 租户管理员）触发，先校验身份与租户边界
    await authorize_task(msg.user_id, msg.tenant_id, ["rbac:read"])
    channel = msg.payload.get("channel")
    content = msg.payload.get("content", "")
    # TODO: 接邮件 / 企微 / Webhook / 工单具体渠道；失败重试 + 死信
    logger.info(f"[notify] channel={channel} tenant={msg.tenant_id} content={content}")
