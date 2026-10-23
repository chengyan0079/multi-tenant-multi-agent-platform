"""可观测（Langfuse / Prometheus）。"""
from __future__ import annotations

from backend.core.tracing import tracing
from backend.server.base_manager import BaseManager


class ObservabilityManager(BaseManager):
    async def start(self) -> None:
        # tracing 单例已在导入时初始化；此处可挂 Prometheus 指标采集（M9 填充）
        return None

    async def stop(self) -> None:
        return None
