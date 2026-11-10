"""审计批量落库 handler（真实落库，低风险，作为 MQ 接入的首个验证点）。

业务侧把审计写入改为 enqueue_task(TaskType.AUDIT_FLUSH, ...)，由本 handler 异步落库，
削峰且不阻塞主请求。
"""

from __future__ import annotations

from backend.broker.envelope import TaskMessage
from backend.broker.security import authorize_task
from backend.data.dao.ops.audit_dao import AuditDao


async def handle_audit_flush(msg: TaskMessage) -> None:
    # 审计写入限超管 / 租户管理员（能查看审计者才允许补写）
    await authorize_task(msg.header.user_id, msg.header.tenant_id, ["audit:read"])
    p = msg.data
    await AuditDao.write(
        tenant_id=msg.header.tenant_id if msg.header.tenant_id is not None else 0,
        user_id=msg.header.user_id,
        action=p["action"],
        target=p.get("target", ""),
        detail=p.get("detail", ""),
        result=p.get("result", "成功"),
        trace_id=p.get("trace_id"),
        ip=p.get("ip"),
    )
