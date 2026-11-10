"""安全启动项（认证/护栏依赖在请求期生效，此处仅占位校验配置）。"""

from __future__ import annotations

from backend.app_state import app_state
from backend.common.logger import get_logger
from backend.server.base_manager import BaseManager, HealthInfo


class SecurityManager(BaseManager):
    async def start(self) -> None:
        if not app_state.settings.security.jwt_secret:
            get_logger("security").warning("JWT_SECRET 未配置，认证将不可用")
        return None

    async def stop(self) -> None:
        return None

    async def health(self) -> HealthInfo:
        if not app_state.settings.security.jwt_secret:
            return HealthInfo(status="degraded", detail="JWT_SECRET 未配置，认证不可用")
        return HealthInfo(status="running")
