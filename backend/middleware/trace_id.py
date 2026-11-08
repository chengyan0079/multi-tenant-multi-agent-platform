"""trace_id - 全链路 trace_id 注入（设计文档 §9 可观测）

每个请求生成/透传 trace_id，写入 contextvars（日志 patcher 读取）。
支持上游通过 X-Trace-Id 头传入，便于跨服务串联；上游不带则后端自行生成。

实现为**纯 ASGI 中间件**：BaseHTTPMiddleware 与 SSE（EventSourceResponse）等
流式响应组合时会触发 `RuntimeError: No response returned`，这里改为直接包装
send，兼容流式响应。
"""
from __future__ import annotations

import uuid6
from starlette.datastructures import Headers, MutableHeaders

from backend.app_state import tenant_id_ctx, user_id_ctx
from backend.common.logger import trace_id_ctx


class TraceIdMiddleware:
    """请求级 trace_id 注入与清理（纯 ASGI）。"""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        raw = (Headers(scope=scope).get("X-Trace-Id") or "").strip()
        trace_id = raw or uuid6.uuid7().hex

        token = trace_id_ctx.set(trace_id)
        # 认证尚未发生，租户/用户上下文先置空；认证依赖会在请求内覆盖
        t_token = tenant_id_ctx.set(None)
        u_token = user_id_ctx.set(None)

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["X-Trace-Id"] = trace_id
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            trace_id_ctx.reset(token)
            tenant_id_ctx.reset(t_token)
            user_id_ctx.reset(u_token)
