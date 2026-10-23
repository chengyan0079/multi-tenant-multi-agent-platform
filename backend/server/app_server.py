"""
app_server - 按 order 顺序启动 Manager，逆序停机（设计文档 §10）

与 RAG-Ultra 同范式：任一启动项失败整体 fail-fast 并回滚已启动项。
entrypoint 在 main.py：装配 AppServer().run()。
"""
from __future__ import annotations

import asyncio
import time
from typing import List, Tuple

from backend.common.logger import get_logger

logger = get_logger("server")


class StartupError(RuntimeError):
    """任一启动项初始化失败，阻断服务启动。"""


class AppServer:
    """按 order 排序启动 Manager；停机时逆序释放。"""

    def __init__(self, name: str = "agent-platform") -> None:
        self.name = name
        # (order, name, mgr)
        self._items: List[Tuple[int, str, "BaseManager"]] = []

    def register(self, manager: "BaseManager", order: int = 100) -> "AppServer":
        """登记启动项；order 越小越先启动。返回 self 以支持链式调用。"""
        self._items.append((order, manager.__class__.__name__, manager))
        self._items.sort(key=lambda x: x[0])
        return self

    async def _start_one(self, name: str, mgr: "BaseManager") -> None:
        logger.info(f"[{self.name}] starting {name} ...")
        t0 = time.perf_counter()
        await mgr.start()
        logger.info(f"[{self.name}] {name} 启动完成，耗时 {(time.perf_counter() - t0) * 1000:.1f} ms")

    async def start_all(self) -> None:
        started: List[Tuple[str, "BaseManager"]] = []
        for order, name, mgr in self._items:
            try:
                await self._start_one(name, mgr)
                started.append((name, mgr))
            except Exception as exc:
                logger.opt(exception=exc).error(f"[{self.name}] 启动失败：{name} - {exc}")
                await self._reverse_stop(started)
                raise StartupError(f"{name} 启动失败") from exc
        logger.info(f"[{self.name}] 全部启动项完成，共 {len(started)} 项")

    async def stop_all(self) -> None:
        await self._reverse_stop([(n, m) for _, n, m in self._items])

    async def _reverse_stop(self, started: List[Tuple[str, "BaseManager"]]) -> None:
        for name, mgr in reversed(started):
            try:
                logger.info(f"[{self.name}] stopping {name} ...")
                await mgr.stop()
            except Exception:
                logger.exception(f"[{self.name}] stop failed: {name}")
