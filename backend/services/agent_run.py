"""长任务执行入口：多 Agent 串联 / 长推理。"""

from __future__ import annotations

from typing import Any

from backend.common.logger import logger


async def run_long_task(
    *,
    thread_id: str | None,
    plan: Any,
    tenant_id: int | None,
    user_id: int,
) -> None:
    """执行一条长任务，结果异步推送给前端。

    TODO(agent.run)：
    1. 由 plan 解析出要串联的 Agent 列表，交给 app_state.orchestrator 执行；
    2. 执行过程与结果写入 Redis Stream（key 带 thread_id），
       由持有 SSE 连接的 uvicorn worker 订阅后推给前端（设计文档 §9）；
    3. 中途失败要写终态事件，避免前端一直等待。
    注意：worker 与 HTTP 进程不共享内存，不能直接回调 SSE。
    """
    logger.warning(
        f"[agent.run] 长任务执行未接入 thread={thread_id} "
        f"tenant={tenant_id} user={user_id} plan={plan}"
    )
