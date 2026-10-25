"""
tracing - Langfuse trace 封装（设计文档 §9 可观测）

无 Langfuse 配置时降级为本地 no-op，不阻断主链路。trace_id 取自 contextvars，
与 JSON 日志共用同一链路标识。
"""
from __future__ import annotations

from typing import Optional

from backend.app_state import app_state, get_trace_id
from backend.common.logger import get_logger

logger = get_logger("tracing")


class TracingClient:
    """轻封装：observation 开启时上报，否则 no-op。"""

    def __init__(self) -> None:
        self._enabled = bool(
            app_state.settings.observability.langfuse_host
            and app_state.settings.observability.langfuse_public_key
        )

    def event(self, name: str, metadata: Optional[dict] = None) -> None:
        """记录一次事件（节点/工具/状态转移）。未开启可观测时直接返回。"""
        if not self._enabled:
            return
        trace_id = get_trace_id()
        logger.debug(f"trace[{trace_id}] {name} {metadata or {}}")

    def span(self, name: str, metadata: Optional[dict] = None):
        """占位 span 上下文管理器；真实实现接入 Langfuse 客户端。"""
        return _NoopSpan()


class _NoopSpan:
    def __enter__(self) -> "_NoopSpan":
        return self

    def __exit__(self, *exc: object) -> None:
        return None


tracing = TracingClient()
