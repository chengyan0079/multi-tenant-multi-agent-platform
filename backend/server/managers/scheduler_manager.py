"""定时任务（见 docs/消息队列对接设计 §10）：扫 agent_escalation 超时 pending，发 notify.send 提醒。

用 asyncio 定时协程（不引入 APScheduler 额外依赖，贴合全 async 栈）。
周期扫描超时未处理的人工转接，经 Outbox 发 notify.send（由 BrokerManager 投递协程发 MQ），
发后写 last_reminder_at 避免重复提醒。与 broker 同启用（提醒需 MQ 外发）。
"""
from __future__ import annotations

import asyncio

from sqlalchemy import text

from backend.app_state import app_state
from backend.broker.publish import publish_task
from backend.common.logger import logger
from backend.data.sql import execute_write, fetch_all, session_scope
from backend.server.base_manager import BaseManager, HealthInfo

_SCAN = text(
    "SELECT id, tenant_id, user_id, thread_id, reason FROM agent_escalation "
    "WHERE status='pending' AND last_reminder_at IS NULL "
    "AND create_at < now() - make_interval(mins => :timeout) "
    "ORDER BY create_at ASC LIMIT :limit"
)
_MARK_REMINDED = text("UPDATE agent_escalation SET last_reminder_at=now() WHERE id=:id")


class SchedulerManager(BaseManager):
    def __init__(self) -> None:
        super().__init__("scheduler")
        self._stop = asyncio.Event()

    async def start(self) -> None:
        self._task = asyncio.create_task(self._loop())
        logger.info("定时任务协程已启动（HITL 超时扫描）")

    async def stop(self) -> None:
        self._stop.set()
        if hasattr(self, "_task"):
            self._task.cancel()

    async def health(self) -> HealthInfo:
        return HealthInfo(status="running" if not self._stop.is_set() else "stopped")

    async def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                await self._scan()
            except asyncio.CancelledError:  # 协程被取消，干净退出
                break
            except Exception as exc:  # noqa: BLE001
                logger.exception(f"定时扫描异常：{exc}")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=app_state.settings.scheduler.scan_interval)
            except asyncio.TimeoutError:
                continue

    async def _scan(self) -> None:
        async with session_scope() as session:
            rows = await fetch_all(
                session,
                _SCAN,
                {"timeout": app_state.settings.scheduler.escalation_timeout_min, "limit": 50},
            )
        for r in rows:
            await publish_task(
                "notify.send",
                type="notify.send",
                tenant_id=r["tenant_id"],
                user_id=r["user_id"],
                payload={
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
                await session.commit()
