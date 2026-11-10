"""长任务 handler（多 Agent 串联 / 长推理）。

handler 只做鉴权与消息结构，执行逻辑见 services/agent_run.py。
"""

from __future__ import annotations

from backend.broker.envelope import TaskMessage
from backend.broker.security import authorize_task
from backend.services.agent_run import run_long_task


async def handle_agent_run(msg: TaskMessage) -> None:
    # 长任务仅超管可发起（agent:write 仅 admin 角色持有）
    await authorize_task(msg.header.user_id, msg.header.tenant_id, ["agent:write"])
    await run_long_task(
        thread_id=msg.data.get("thread_id"),
        plan=msg.data.get("plan"),
        tenant_id=msg.header.tenant_id,
        user_id=msg.header.user_id,
    )
