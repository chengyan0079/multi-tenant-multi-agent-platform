"""定时任务（通用定时器，见 docs/消息队列对接设计 §10）。

支持注册多个扫描任务（job），每个 job 按各自间隔独立调度；job 协程异常被捕获并记录，
不影响其它 job。不依赖 broker：job 是否用 MQ 由各自实现决定（escalation 用 Outbox，
broker 关时提醒缓冲不丢；resume 超时仅本地 UPDATE，无需 MQ）。

现有 job：
- escalation_timeout：HITL 转人工超时提醒（publish notify.send，经 Outbox → MQ 外发）；
- resume_review_timeout：resume 评审 processing 超时未完成的记录批量标 failed。

新增扫描任务：在 _register_default_jobs 里 register(name, interval, coro) 即可。
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Awaitable, Callable

from sqlalchemy import text

from backend.app_state import app_state
from backend.broker.publish import enqueue_task
from backend.broker.types import TaskType
from backend.common.logger import logger
from backend.data.sql import execute_write, fetch_all, session_scope
from backend.server.base_manager import BaseManager, HealthInfo


@dataclass
class ScanJob:
    """一个周期扫描任务。"""

    name: str
    interval: float  # 调度间隔（秒）
    coro: Callable[[], Awaitable[None]]
    _next_run: float = 0.0


_ESCALATION_SCAN = text(
    "SELECT id, tenant_id, user_id, thread_id, reason FROM agent_escalation "
    "WHERE status='pending' AND last_reminder_at IS NULL "
    "AND create_at < now() - make_interval(mins => :timeout) "
    "ORDER BY create_at ASC LIMIT :limit"
)
_MARK_REMINDED = text("UPDATE agent_escalation SET last_reminder_at=now() WHERE id=:id")

_RESUME_TIMEOUT_UPDATE = text(
    "UPDATE agent_resume_reviews "
    "SET status='failed', error_msg='评审超时' "
    "WHERE status='processing' "
    "AND create_at < now() - make_interval(mins => :timeout)"
)


class SchedulerManager(BaseManager):
    def __init__(self) -> None:
        super().__init__("scheduler")
        self._stop = asyncio.Event()
        self._jobs: list[ScanJob] = []

    def register(self, name: str, interval: float, coro: Callable[[], Awaitable[None]]) -> None:
        """注册一个周期任务；interval 为调度间隔（秒）。"""
        self._jobs.append(ScanJob(name=name, interval=interval, coro=coro))

    def _register_default_jobs(self) -> None:
        s = app_state.settings.scheduler
        self.register("escalation_timeout", s.scan_interval, self._scan_escalation)
        self.register("resume_review_timeout", s.scan_interval, self._scan_resume_timeout)

    async def start(self) -> None:
        self._register_default_jobs()
        self._task = asyncio.create_task(self._loop())
        logger.info("定时任务协程已启动（jobs=%s）", [j.name for j in self._jobs])

    async def stop(self) -> None:
        self._stop.set()
        if hasattr(self, "_task"):
            self._task.cancel()

    async def health(self) -> HealthInfo:
        return HealthInfo(status="running" if not self._stop.is_set() else "stopped")

    async def _loop(self) -> None:
        loop = asyncio.get_running_loop()
        for j in self._jobs:
            j._next_run = loop.time()
        while not self._stop.is_set():
            now = loop.time()
            for j in self._jobs:
                if now >= j._next_run:
                    try:
                        await j.coro()
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:  # noqa: BLE001 - 单 job 异常不影响其它 job
                        logger.exception(f"定时任务[{j.name}]执行异常：{exc}")
                    j._next_run = loop.time() + j.interval
            if not self._jobs:
                await self._stop.wait()
                continue
            soonest = min(j._next_run for j in self._jobs)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=max(0.0, soonest - loop.time()))
            except asyncio.TimeoutError:
                continue

    # ---- job 实现 ----

    async def _scan_escalation(self) -> None:
        """HITL 转人工超时提醒：扫超时 pending，发 notify.send，写 last_reminder_at 防重复。"""
        async with session_scope() as session:
            rows = await fetch_all(
                session,
                _ESCALATION_SCAN,
                {"timeout": app_state.settings.scheduler.escalation_timeout_min, "limit": 50},
            )
        for r in rows:
            await enqueue_task(
                TaskType.NOTIFY_SEND,
                tenant_id=r["tenant_id"],
                user_id=r["user_id"],
                data={
                    "channel": "webhook",
                    "content": (
                        f"HITL 转人工超时提醒：会话 {r['thread_id']} 待处理"
                        f"（原因：{r['reason']}）"
                    ),
                    "escalation_id": r["id"],
                },
            )
            async with session_scope() as session:
                await execute_write(session, _MARK_REMINDED, {"id": r["id"]})

    async def _scan_resume_timeout(self) -> None:
        """resume 评审兜底：processing 且超过 resume_timeout_min 未完成的记录批量标 failed。"""
        async with session_scope() as session:
            rowcount = await execute_write(
                session,
                _RESUME_TIMEOUT_UPDATE,
                {"timeout": app_state.settings.scheduler.resume_timeout_min},
            )
            if rowcount:
                logger.info(f"[resume.timeout] 超时未完成的评审标记 failed 共 {rowcount} 条")
