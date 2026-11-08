"""跨副本配置刷新：Redis 版本号信号 + 各副本定时拉取。

背景：AgentRegistry / LLMFactory / PluginRegistry 都是进程内缓存，启动时从 DB 一次性
加载。超管在后台改配置后，只有处理该请求的副本刷新了本地内存，其它副本仍是旧数据。

方案（不再走 MQ 广播）：
- 变更方 `publish(targets)` 对**每个 target 独立的 Redis key** 执行 INCR，写入单调递增版本号；
  Redis 里只放"变了"的信号，不放配置内容——DB 始终是权威源，避免双写一致性问题。
- 每个副本由 SchedulerManager 定时 `poll_once()`：一次 MGET 拿全部版本号，与本地
  `_seen_versions` 比对，仅对变化的 target 调用对应 reload；INCR 单调，天然幂等，
  不受时钟回拨影响（替代旧 handler 里的 `_seen_ts` 时间戳）。
- 启动时各副本本来就 `load_from_db()` 拿最新，故只需把首次 MGET 的结果记为基线，
  不必在启动时重复 reload。晚启动的副本天然能看到最新配置。
- Redis 不可用：publish 记 warning 但不阻断管理接口（本副本已刷新）；poll 侧按
  `FALLBACK_RELOAD_INTERVAL_S` 退化为定时全量 reload，保证最终一致。

key 前缀沿用 `prompts_cache.py` 的 `agent:prompt:{data_id}` 风格。
"""
from __future__ import annotations

import asyncio
import time
from typing import Awaitable, Callable

from backend.app_state import app_state
from backend.common.logger import logger
from backend.server.managers.model_manager import ModelManager
from backend.server.managers.plugin_manager import reload_plugins

# 可按 target 独立刷新的三类进程内缓存
TARGETS: tuple[str, ...] = ("agent_registry", "llm_factory", "plugin_registry")

_KEY_PREFIX = "agent:config:refresh:"
# Redis 长时间不可用时，退化为按此间隔全量 reload（秒），保证最终一致
FALLBACK_RELOAD_INTERVAL_S = 300


def _key(target: str) -> str:
    return f"{_KEY_PREFIX}{target}"


# 各副本进程内自己维护的"已应用版本号"；首次 MGET 只记基线、不 reload
_seen_versions: dict[str, int] = {}
_initialized = False
_last_fallback_reload = 0.0
_reload_lock = asyncio.Lock()


def _reloaders() -> dict[str, Callable[[], Awaitable[None]]]:
    """target → reload 协程；延迟取 app_state，避免模块导入期依赖启动顺序。"""

    async def _agent_registry() -> None:
        registry = app_state.agent_registry
        if registry is not None:
            await registry.refresh()

    async def _llm_factory() -> None:
        await ModelManager().reload()

    async def _plugin_registry() -> None:
        await reload_plugins()

    return {
        "agent_registry": _agent_registry,
        "llm_factory": _llm_factory,
        "plugin_registry": _plugin_registry,
    }


async def publish(*targets: str) -> None:
    """配置变更后发布刷新信号（每个 target 独立 key，INCR 单调递增）。

    由管理端点调用；调用方在此之前已刷新本副本内存，故 Redis 写失败只告警、
    不抛错阻断接口，其它副本由 poll 的兜底全量 reload 最终收敛。
    """
    r = app_state.redis
    if r is None:
        logger.warning("config.refresh: Redis 未就绪，跳过版本写入（其它副本走兜底全量 reload）")
        return
    for target in targets:
        if target not in TARGETS:
            logger.warning(f"config.refresh: 未知 target={target}，忽略")
            continue
        try:
            await r.incr(_key(target))
        except Exception as exc:  # noqa: BLE001 - Redis 抖动不阻断管理接口
            logger.warning(f"config.refresh: 版本写入失败 target={target}：{exc}")
    logger.debug(f"config.refresh: publish targets={list(targets)}")


async def _reload_all() -> None:
    """全量 reload（Redis 不可用时的兜底，以及版本首次出现时的稳妥处理）。"""
    for target, reload_coro in _reloaders().items():
        try:
            await reload_coro()
        except Exception as exc:  # noqa: BLE001 - 单个 target 失败不影响其它
            logger.exception(f"config.refresh: reload 失败 target={target}：{exc}")


async def poll_once() -> None:
    """各副本定时调用：MGET 比对版本号，仅刷新变化的 target。"""
    global _initialized, _last_fallback_reload

    r = app_state.redis
    if r is None:
        await _fallback_reload()
        return

    try:
        values = await r.mget([_key(t) for t in TARGETS])
    except Exception as exc:  # noqa: BLE001 - Redis 抖动走兜底，不阻断调度循环
        logger.warning(f"config.refresh: 版本读取失败，走兜底：{exc}")
        await _fallback_reload()
        return

    versions = {
        target: int(v) if v not in (None, b"", "") else 0
        for target, v in zip(TARGETS, values)
    }

    # 首次轮询只建立基线：启动时已从 DB 加载最新配置，重复 reload 无意义
    if not _initialized:
        _seen_versions.update(versions)
        _initialized = True
        logger.debug(f"config.refresh: 基线版本 {versions}")
        return

    changed = [t for t in TARGETS if versions.get(t, 0) > _seen_versions.get(t, 0)]
    if not changed:
        _seen_versions.update(versions)
        return

    async with _reload_lock:
        reloaders = _reloaders()
        for target in changed:
            try:
                await reloaders[target]()
                _seen_versions[target] = versions[target]
                logger.info(f"config.refresh: 已刷新 target={target} version={versions[target]}")
            except Exception as exc:  # noqa: BLE001 - 失败不更新版本，下轮自动重试
                logger.exception(f"config.refresh: 刷新失败 target={target}：{exc}")
        # 未变化的 target 同步到最新值，避免下轮误判
        for target in TARGETS:
            if target not in changed:
                _seen_versions[target] = versions[target]


async def _fallback_reload() -> None:
    """Redis 不可用时的最终一致性兜底：按间隔全量 reload。"""
    global _last_fallback_reload
    now = time.monotonic()
    if now - _last_fallback_reload < FALLBACK_RELOAD_INTERVAL_S:
        return
    _last_fallback_reload = now
    logger.warning("config.refresh: Redis 不可用，执行兜底全量 reload")
    async with _reload_lock:
        await _reload_all()
