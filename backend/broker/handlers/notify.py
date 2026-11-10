"""通知外发 handler（HITL 确认后外发动作）。

handler 只做鉴权与消息结构，渠道分发见 services/notification.py。
"""

from __future__ import annotations

from backend.broker.envelope import TaskMessage
from backend.broker.security import authorize_task
from backend.services.notification import send_notification


async def handle_notify_send(msg: TaskMessage) -> None:
    # 通知由具 RBAC 权限者（超管 / 租户管理员）触发，先校验身份与租户边界
    await authorize_task(msg.header.user_id, msg.header.tenant_id, ["rbac:read"])
    data = msg.data
    # channel / content 是通用字段，其余原样透传给具体渠道
    extra = {k: v for k, v in data.items() if k not in ("channel", "content")}
    await send_notification(
        channel=data.get("channel"),
        tenant_id=msg.header.tenant_id,
        user_id=msg.header.user_id,
        content=data.get("content", ""),
        **extra,
    )
