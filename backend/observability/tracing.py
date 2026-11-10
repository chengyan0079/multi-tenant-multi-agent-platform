"""Langfuse trace 封装：适配 langfuse SDK 5.x（OTEL 采集），未配置/不可用时降级 no-op。

设计：
- 模块级单例 `tracing`，由 ObservabilityManager.start() 调 configure() 初始化客户端；
- SDK 5.x 构造 Langfuse 即注册为全局单例，CallbackHandler 用 public_key 取回该客户端；
- 5.x 的 LangChain 集成位于 langfuse.langchain，原生要求 langchain-core>=1，
  本项目即 1.x，无需任何兼容 shim；
- trace_id 与 JSON 日志共用（uuid7 hex，符合 W3C trace id 格式）；
- tenant_id / user_id / session_id 经 LangChain config.metadata 注入
  （langfuse_session_id / langfuse_user_id 等约定键）。
"""

from __future__ import annotations

from typing import Any, Optional

from backend.app_state import (
    app_state,
    get_tenant_id,
    get_trace_id,
    get_user_id,
)
from backend.common.logger import get_logger

logger = get_logger("tracing")

# langfuse 为可选依赖：未安装 / 版本不兼容时整模块降级，不阻断导入。
try:
    from langfuse import Langfuse
    from langfuse.langchain import CallbackHandler

    _LANGFUSE_AVAILABLE = True
except Exception as e:  # pragma: no cover - 依赖缺失/不兼容时降级
    logger.exception(f"langfuse 不可用（{e!r}），trace 降级 no-op")
    Langfuse = None  # type: ignore[assignment]
    CallbackHandler = None  # type: ignore[assignment]
    _LANGFUSE_AVAILABLE = False


def _str_or_none(v: Any) -> Optional[str]:
    return str(v) if v is not None else None


class TracingClient:
    """轻封装：observation 开启时上报，否则 no-op。"""

    def __init__(self) -> None:
        self._client: Optional["Langfuse"] = None
        self._enabled = False

    # ---- 生命周期：由 ObservabilityManager.start 调用（幂等）----
    def configure(self) -> None:
        obs = app_state.settings.observability
        if not (obs.langfuse_base_url and obs.langfuse_public_key and obs.langfuse_secret_key):
            self._enabled = False
            logger.warning(
                "Langfuse 未启用（LANGFUSE_BASE_URL/PUBLIC_KEY/SECRET_KEY 不全），trace 降级 no-op"
            )
            return
        if not _LANGFUSE_AVAILABLE:
            self._enabled = False
            logger.warning("langfuse SDK 未安装，trace 降级 no-op")
            return
        try:
            # 5.x 用 base_url；构造即注册全局单例，供 get_client() 取用
            self._client = Langfuse(
                public_key=obs.langfuse_public_key,
                secret_key=obs.langfuse_secret_key,
                base_url=obs.langfuse_base_url,
            )
            self._enabled = True
        except Exception as e:  # 软降级：可观测不可用不应拖垮主链路
            self._enabled = False
            self._client = None
            logger.exception(f"Langfuse 初始化失败，trace 降级 no-op：{e}")
            return

        logger.info(f"Langfuse 已启用：host={obs.langfuse_base_url}（SDK 5.x / OTEL）")
        # 连通性自检放在初始化 try 之外：校验失败只告警，不关闭已启用的 tracing
        self._auth_check()

    def _auth_check(self) -> None:
        """启动期校验凭据与服务端连通性；失败仅告警，不影响 enabled（软降级）。"""
        try:
            ok = self._client.auth_check()
        except Exception as e:
            logger.exception(
                f"Langfuse 凭据/服务端连通性校验失败（{e}）："
                "请确认 LANGFUSE_* 密钥属于当前实例、且服务端版本与 SDK 5.x 兼容"
            )
            return
        if not ok:
            logger.warning("Langfuse 凭据校验未通过：请检查 LANGFUSE_PUBLIC_KEY/SECRET_KEY")

    @property
    def enabled(self) -> bool:
        return self._enabled

    # ---- LangChain 集成：把 handler 并入图调用的 callbacks ----
    def with_callbacks(self, cfg: Optional[dict] = None) -> dict:
        """返回并入 Langfuse CallbackHandler 的 LangChain config（保留已有回调）。

        在 graph.ainvoke(inputs, config=tracing.with_callbacks(cfg)) 处调用即可。
        SDK 5.x 不再由 handler 接收 session_id/user_id/metadata，改由 config.metadata
        中的 langfuse_session_id / langfuse_user_id 等约定键传入；trace_id 通过
        trace_context 与 JSON 日志共用。
        """
        if not self._enabled or self._client is None:
            return cfg or {}
        base = dict(cfg or {})
        configurable = base.get("configurable")
        thread_id = (
            configurable.get("thread_id") if isinstance(configurable, dict) else None
        )
        obs = app_state.settings.observability

        handler = CallbackHandler(
            public_key=obs.langfuse_public_key,
            trace_context={"trace_id": get_trace_id()},
        )

        metadata = dict(base.get("metadata") or {})
        metadata.setdefault(
            "langfuse_session_id", _str_or_none(thread_id) or get_trace_id()
        )
        user_id = _str_or_none(get_user_id())
        if user_id:
            metadata.setdefault("langfuse_user_id", user_id)
        tenant_id = _str_or_none(get_tenant_id())
        if tenant_id:
            metadata.setdefault("tenant_id", tenant_id)
        base["metadata"] = metadata

        existing = list(base.get("callbacks") or [])
        existing.append(handler)
        base["callbacks"] = existing
        return base

    # ---- 兼容旧调用（保留接口，避免破坏潜在调用方）----
    def event(self, name: str, metadata: Optional[dict] = None) -> None:
        if not self._enabled:
            return
        logger.debug(f"trace[{get_trace_id()}] {name} {metadata or {}}")

    def span(self, name: str, metadata: Optional[dict] = None):
        return _NoopSpan()

    def flush(self) -> None:
        if self._enabled and self._client is not None:
            try:
                self._client.flush()
            except Exception as e:  # pragma: no cover
                logger.exception(f"Langfuse flush 失败：{e}")


class _NoopSpan:
    def __enter__(self) -> "_NoopSpan":
        return self

    def __exit__(self, *exc: object) -> None:
        return None


tracing = TracingClient()
