"""按阶段分组 gather 启动 Manager、逆序停机；启动失败整体 fail-fast 并回滚。"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Tuple

from backend.app_state import app_state
from backend.common.logger import get_logger
from backend.server.base_manager import BaseManager, HealthInfo, ManagerStatus

logger = get_logger("server")


def _fmt(seconds: float) -> str:
    """耗时自适应格式化：不足 1s 用 ms，否则用 s（便于对齐不同量级的启动项）。"""
    return f"{seconds * 1000:.1f} ms" if seconds < 1 else f"{seconds:.2f} s"


class StartupError(RuntimeError):
    """任一启动项初始化失败，阻断服务启动。"""


class AppServer:
    """按 order 分阶段并行启动 Manager；停机时逆序释放。"""

    def __init__(self, name: str = "agent-platform") -> None:
        self.name = name
        # (order, name, mgr)
        self._items: List[Tuple[int, str, BaseManager]] = []
        # 最近一次启动的单项耗时（秒），供健康检查/运维排查读取
        self.startup_timings: Dict[str, float] = {}
        self.startup_total_s: float = 0.0
        self.started_at: datetime | None = None

    def register(self, manager: BaseManager, order: int = 100) -> AppServer:
        """登记启动项；order 越小越先启动。返回 self 以支持链式调用。"""
        self._items.append((order, manager.name, manager))
        self._items.sort(key=lambda x: x[0])
        return self

    def _group_by_order(self) -> List[List[Tuple[int, str, BaseManager]]]:
        """按 order 分组，同组内顺序无关（将并行执行）。"""
        groups: dict[int, List[Tuple[int, str, BaseManager]]] = defaultdict(list)
        for item in self._items:
            groups[item[0]].append(item)
        return [groups[order] for order in sorted(groups)]

    async def _start_one(self, name: str, mgr: BaseManager) -> float:
        """启动单个 manager，返回耗时（秒）。失败时置 FAILED 并抛出。"""
        mgr._set_status(ManagerStatus.STARTING)
        logger.info(f"[{self.name}] starting {name} ...")
        t0 = time.perf_counter()
        try:
            await mgr.start()
        except Exception:
            elapsed = time.perf_counter() - t0
            mgr._set_status(ManagerStatus.FAILED)
            logger.exception(f"[{self.name}] {name} 启动失败，耗时 {_fmt(elapsed)}")
            raise
        elapsed = time.perf_counter() - t0
        mgr._set_status(ManagerStatus.RUNNING)
        extra = ""
        try:
            stats = await mgr.startup_stats()
            if stats:
                extra = f"，{stats}"
        except Exception as exc:  # noqa: BLE001 - 统计失败不影响启动
            logger.warning(f"[{self.name}] {name} 启动统计失败: {exc}")
        logger.info(f"[{self.name}] {name} 启动完成，耗时 {_fmt(elapsed)}{extra}")
        return elapsed

    def _log_slowest(self, timings: Dict[str, float]) -> None:
        """输出耗时 Top5，便于定位启动瓶颈。"""
        if not timings:
            return
        slow = sorted(timings.items(), key=lambda kv: kv[1], reverse=True)[:5]
        detail = "、".join(f"{n}({_fmt(s)})" for n, s in slow)
        logger.info(f"[{self.name}] 启动耗时 Top{len(slow)}：{detail}")

    async def start_all(self) -> None:
        started: List[Tuple[str, BaseManager]] = []
        timings: Dict[str, float] = {}
        phases = self._group_by_order()

        self.started_at = datetime.now()
        t_total = time.perf_counter()
        logger.info(
            f"[{self.name}] ===== 开始启动 ===== "
            f"时刻 {self.started_at:%Y-%m-%d %H:%M:%S}，"
            f"共 {len(self._items)} 项 / {len(phases)} 个阶段"
        )

        for idx, phase in enumerate(phases, 1):
            t_phase = time.perf_counter()
            # 同阶段内并行启动；return_exceptions 让整阶段跑完再统一判定
            results = await asyncio.gather(
                *[self._start_one(name, mgr) for _, name, mgr in phase],
                return_exceptions=True,
            )
            phase_elapsed = time.perf_counter() - t_phase
            failed: List[Tuple[str, BaseException]] = []
            for (_, name, mgr), result in zip(phase, results):
                if isinstance(result, BaseException):
                    failed.append((name, result))
                else:
                    started.append((name, mgr))
                    timings[name] = result  # type: ignore[assignment]

            if failed:
                logger.error(
                    f"[{self.name}] 阶段 {idx}/{len(phases)} 失败，已耗时 {_fmt(phase_elapsed)}"
                )
                for name, exc in failed:
                    logger.opt(exception=exc).error(f"[{self.name}] 启动失败：{name} - {exc}")
                # 记录失败前的统计，便于定位问题
                self.startup_timings = timings
                self.startup_total_s = time.perf_counter() - t_total
                self._log_slowest(timings)
                # 同阶段已成功的项也在 started 中，一并回滚
                await self._reverse_stop(started)
                names = "、".join(n for n, _ in failed)
                raise StartupError(f"{names} 启动失败") from failed[0][1]

            logger.info(
                f"[{self.name}] 阶段 {idx}/{len(phases)} 完成，"
                f"{len(phase)} 项并行，耗时 {_fmt(phase_elapsed)}"
            )

        total = time.perf_counter() - t_total
        self.startup_timings = timings
        self.startup_total_s = total
        # 记为「服务可用时刻」：/health 与 /dashboard 据此算 uptime，含启动耗时才准确
        app_state.started_at = datetime.now()
        logger.info(
            f"[{self.name}] ===== 启动完成 ===== "
            f"时刻 {app_state.started_at:%Y-%m-%d %H:%M:%S}，"
            f"共 {len(started)} 项 / {len(phases)} 个阶段，"
            f"总耗时 {_fmt(total)}"
        )
        self._log_slowest(timings)
        # 启动完成后对全部组件做一次探活，逐一打印状态（同 /health 复用此逻辑）
        await self.health_report()

    async def health_report(self) -> dict:
        """汇总各组件健康状态：逐个探活、记录日志、判定整体状态。

        返回结构可直接作为 /health 响应体。整体状态规则：
          - 任一组件 failed/down/stopping → down
          - 其余存在 degraded/starting   → degraded
          - 全部 running                   → up
        """
        components: list[dict] = []
        for _, name, mgr in self._items:
            try:
                info = await mgr.health()
            except Exception as exc:  # 探活自身抛错也记为不可用
                info = HealthInfo(status="down", detail=f"{type(exc).__name__}: {exc}")
            components.append({"name": name, "status": info.status, "detail": info.detail})
            # 按状态分级：running/starting -> info；degraded -> warning；down/failed/stopping -> error
            if info.status in ("down", "failed", "stopping"):
                _log = logger.error
            elif info.status == "degraded":
                _log = logger.warning
            else:
                _log = logger.info
            if info.detail:
                _log(f"[{self.name}] 组件状态 {name}: {info.status} ({info.detail})")
            else:
                _log(f"[{self.name}] 组件状态 {name}: {info.status}")

        overall = "up"
        if any(c["status"] in ("failed", "down", "stopping") for c in components):
            overall = "down"
        elif any(c["status"] in ("degraded", "starting") for c in components):
            overall = "degraded"

        return {
            "status": overall,
            "started_at": app_state.started_at.strftime("%Y-%m-%d %H:%M:%S")
            if app_state.started_at
            else None,
            "components": components,
        }

    async def stop_all(self) -> None:
        t0 = time.perf_counter()
        items = [(n, m) for _, n, m in self._items]
        logger.info(f"[{self.name}] ===== 开始停机 ===== 共 {len(items)} 项")
        await self._reverse_stop(items)
        logger.info(f"[{self.name}] ===== 停机完成 ===== 总耗时 {_fmt(time.perf_counter() - t0)}")

    async def _reverse_stop(self, started: List[Tuple[str, BaseManager]]) -> None:
        for name, mgr in reversed(started):
            t0 = time.perf_counter()
            try:
                mgr._set_status(ManagerStatus.STOPPING)
                logger.info(f"[{self.name}] stopping {name} ...")
                await mgr.stop()
                mgr._set_status(ManagerStatus.STOPPED)
                logger.info(f"[{self.name}] {name} 已停止，耗时 {_fmt(time.perf_counter() - t0)}")
            except Exception:
                mgr._set_status(ManagerStatus.STOPPED)  # 停机失败也标记为已停止
                logger.exception(
                    f"[{self.name}] stop failed: {name}（耗时 {_fmt(time.perf_counter() - t0)}）"
                )
