"""长任务 handler（多 Agent 串联 / 长推理）。

本轮落鉴权与消息结构；执行与结果回传（Redis Stream → SSE）接 TODO。
"""
from __future__ import annotations

from backend.broker.envelope import TaskMessage
from backend.broker.security import authorize_task
from backend.common.logger import logger


async def handle_agent_run(msg: TaskMessage) -> None:
    # 长任务仅超管可发起（agent:write 仅 admin 角色持有）
    await authorize_task(msg.user_id, msg.tenant_id, ["agent:write"])
    thread_id = msg.payload.get("thread_id")
    plan = msg.payload.get("plan")
    # TODO: 调 Orchestrator 执行长任务；结果经 Redis Stream 回传持有 SSE 的 uvicorn worker
    logger.info(f"[agent.run] thread={thread_id} tenant={msg.tenant_id} plan={plan}")
