"""定时任务管理器：注册多 job 独立调度，异常互不影响；支持 config_refresh 与 resume 超时扫描。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Awaitable, Callable

from sqlalchemy import text

from backend.app_state import app_state
from backend.common.logger import logger
from backend.data.sql import execute_write, session_scope
from backend.services.config_refresh import poll_once as poll_config_refresh
from backend.server.base_manager import BaseManager, HealthInfo


@dataclass
class ScanJob:
    """一个周期扫描任务。"""

    name: str
    interval: float  # 调度间隔（秒）
    coro: Callable[[], Awaitable[None]]
    _next_run: float = 0.0


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
        self.register("resume_review_timeout", s.scan_interval, self._scan_resume_timeout)
        self.register("config_refresh_poll", s.config_refresh_interval, poll_config_refresh)

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
