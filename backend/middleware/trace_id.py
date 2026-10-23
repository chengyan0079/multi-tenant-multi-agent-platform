"""
trace_id - 全链路 trace_id 注入（设计文档 §9 可观测）

每个请求生成/透传 trace_id，写入 contextvars（日志 patcher 读取）。
支持上游通过 header 传入，便于跨服务串联。
"""
from __future__ import annotations

import uuid

from starlette.middleware.base import BaseHTTPMiddleware

from backend.app_state import tenant_id_ctx, user_id_ctx
from backend.common.logger import trace_id_ctx


class TraceIdMiddleware(BaseHTTPMiddleware):
    """请求级 trace_id 注入与清理。"""

    async def dispatch(self, request, call_next):
        trace_id = request.headers.get("X-Trace-Id") or uuid.uuid4().hex
        token = trace_id_ctx.set(trace_id)
        # 租户/用户 id 由认证中间件写入 request.state；此处仅置默认值
        t_token = tenant_id_ctx.set(request.state.tenant_id if hasattr(request.state, "tenant_id") else None)
        u_token = user_id_ctx.set(request.state.user_id if hasattr(request.state, "user_id") else None)
        try:
            response = await call_next(request)
            response.headers["X-Trace-Id"] = trace_id
            return response
        finally:
            trace_id_ctx.reset(token)
            tenant_id_ctx.reset(t_token)
            user_id_ctx.reset(u_token)
