"""日志启动项：触发 loguru 配置（控制台 + 文件双写）。"""
from __future__ import annotations

from backend.common.logger import get_logger, setup_logging
from backend.server.base_manager import BaseManager, HealthInfo, ManagerStatus


class LoggingManager(BaseManager):
    async def start(self) -> None:
        # 其余模块在 import 时已通过 get_logger 拿到 loguru 单例，此处统一完成文件/控制台 sink 配置
        setup_logging()
        get_logger("logging").info("日志系统就绪")

    async def health(self) -> HealthInfo:
        # 日志为进程内单例，启动成功即视为可用
        return HealthInfo(
            status="running" if self._status == ManagerStatus.RUNNING else self._status.value
        )
