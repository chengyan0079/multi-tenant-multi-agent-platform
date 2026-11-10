"""可观测（Langfuse）。

软降级原则：Langfuse 不可用（未配置/网络不通/SDK 缺失）时仅告警，不 fail-fast，
避免可观测组件拖垮主链路。
"""

from __future__ import annotations

from backend.observability.tracing import tracing
from backend.server.base_manager import BaseManager, HealthInfo, ManagerStatus


class ObservabilityManager(BaseManager):
    async def start(self) -> None:
        # 按 .env 配置初始化 Langfuse 客户端；未配置/失败则降级 no-op（不阻断启动）
        tracing.configure()

    async def stop(self) -> None:
        tracing.flush()

    async def health(self) -> HealthInfo:
        if tracing.enabled:
            return HealthInfo(status="running", detail="Langfuse 已连接")
        return HealthInfo(status="degraded", detail="Langfuse 未启用/未连接（trace 降级 no-op）")
