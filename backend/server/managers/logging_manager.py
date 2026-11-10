"""日志启动项：触发 loguru 配置（控制台 + 文件双写），并定期把过期日志打包为 zip。"""

from __future__ import annotations

import asyncio

from backend.common.logger import archive_old_logs, get_logger, setup_logging
from backend.server.base_manager import BaseManager, HealthInfo, ManagerStatus

# 归档检查周期：6 小时。切片在每天 00:00 发生，6h 足够在文件超过保留天数后及时归档。
_ARCHIVE_INTERVAL_S = 6 * 3600


class LoggingManager(BaseManager):
    def __init__(self) -> None:
        super().__init__("logging")
        self._stop = asyncio.Event()
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        # 其余模块在 import 时已通过 get_logger 拿到 loguru 单例，此处统一完成文件/控制台 sink 配置
        setup_logging()
        self._task = asyncio.create_task(self._archive_loop())
        get_logger("logging").info("日志系统就绪（超过保留天数的旧日志将打包为 zip）")

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()

    async def health(self) -> HealthInfo:
        # 日志为进程内单例，启动成功即视为可用
        return HealthInfo(
            status="running" if self._status == ManagerStatus.RUNNING else self._status.value
        )

    async def _archive_loop(self) -> None:
        """后台周期归档：把超过 config.logging.days 天的切片日志打包成 zip。"""
        while not self._stop.is_set():
            try:
                created = await asyncio.to_thread(archive_old_logs)
                if created:
                    get_logger("logging").info(
                        f"已归档 {len(created)} 个过期日志为 zip：{[p.name for p in created]}"
                    )
            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001
                get_logger("logging").exception(f"日志归档异常：{exc}")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=_ARCHIVE_INTERVAL_S)
            except asyncio.TimeoutError:
                continue
