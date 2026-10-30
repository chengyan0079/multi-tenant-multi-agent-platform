"""trace_id - 全链路 trace_id 注入（设计文档 §9 可观测）

每个请求生成/透传 trace_id，写入 contextvars（日志 patcher 读取）。
支持上游通过 X-Trace-Id 头传入，便于跨服务串联；上游不带则后端自行生成。

trace_id 以请求为粒度：同一请求内的调用链（含本进程内与打出去的下游调用）共用一个，
不同请求各自独立，缺失不再拒绝（由后端生成）。
"""
from __future__ import annotations

import uuid6

from starlette.middleware.base import BaseHTTPMiddleware

from backend.app_state import tenant_id_ctx, user_id_ctx
from backend.common.logger import trace_id_ctx


class TraceIdMiddleware(BaseHTTPMiddleware):
    """请求级 trace_id 注入与清理。"""

    async def dispatch(self, request, call_next):
        # 上游带则沿用（串联跨服务链路），不带则本请求自己生成；每请求独立。
        raw = (request.headers.get("X-Trace-Id") or "").strip()
        trace_id = raw or uuid6.uuid7().hex

        token = trace_id_ctx.set(trace_id)
        # 租户/用户 id 由认证中间件写入 request.state；此处仅置默认值
        t_token = tenant_id_ctx.set(
            request.state.tenant_id if hasattr(request.state, "tenant_id") else None
        )
        u_token = user_id_ctx.set(
            request.state.user_id if hasattr(request.state, "user_id") else None
        )
        try:
            response = await call_next(request)
            response.headers["X-Trace-Id"] = trace_id
            return response
        finally:
            trace_id_ctx.reset(token)
            tenant_id_ctx.reset(t_token)
            user_id_ctx.reset(u_token)
