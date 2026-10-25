"""可观测（Langfuse / Prometheus）。"""
from __future__ import annotations

from backend.observability.tracing import tracing
from backend.server.base_manager import BaseManager, HealthInfo, ManagerStatus


class ObservabilityManager(BaseManager):
    async def start(self) -> None:
        # tracing 单例已在导入时初始化；此处可挂 Prometheus 指标采集（M9 填充）
        return None

    async def stop(self) -> None:
        return None

    async def health(self) -> HealthInfo:
        # tracing 单例常驻；启动成功即视为可用（指标采集为旁路能力）
        return HealthInfo(
            status="running" if self._status == ManagerStatus.RUNNING else self._status.value
        )
