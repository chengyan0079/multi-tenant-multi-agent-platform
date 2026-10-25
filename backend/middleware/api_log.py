"""
api_log - API 调用日志中间件（纯 ASGI，对齐 RAG-Ultra）

记录每次 API 调用的调用方 / 请求头 / 方法 / 路由 / 状态 / 耗时，
"请求"与"响应"各打一条日志（便于按时间线排障），并合并落一行到 agent_api_call_log。
默认只记元数据，不采集请求体与响应体（`API_LOG_SAVE_BODY=true` 才开启）：
  - 记录体需要缓冲整个请求/响应，大 body 会把表撑大，是列表膨胀的主因；
  - 开启时请求体仅对 POST/PUT/PATCH 的 JSON/文本且长度可控者捕获，捕获后原样重放给下游；
    multipart（文件上传）与超大体不消费、不记录；
  - 开启时响应体逐块透传的同时按上限累积（不阻塞 SSE 流式），超限截断。
实现要点（不用 BaseHTTPMiddleware，纯 ASGI 不吃大文件）：
  - 敏感头（authorization/cookie/...）脱敏为 ***。
"""
from __future__ import annotations

import json
import time
from datetime import datetime
from typing import Any, Callable

from starlette.requests import Request

from backend.app_state import app_state, get_tenant_id, get_user_id, trace_id_ctx
from backend.config import config
from backend.common.logger import logger

_SENSITIVE_HEADERS = frozenset({
    "authorization", "cookie", "set-cookie", "proxy-authorization", "x-api-key",
    "x-auth-signature",
})
_BODY_METHODS = frozenset({"POST", "PUT", "PATCH"})


def _excluded(path: str, prefixes: list[str] | None) -> bool:
    return any(path.startswith(p) for p in (prefixes or []))


def _compact(v: Any) -> str:
    try:
        return json.dumps(v, ensure_ascii=False, separators=(",", ":"))
    except Exception:  # noqa: BLE001
        return str(v)


def _headers_dict(scope: dict, mask: bool = True) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw_key, raw_val in scope.get("headers") or []:
        key = raw_key.decode("latin-1").lower()
        out[key] = "***" if (mask and key in _SENSITIVE_HEADERS) else raw_val.decode("latin-1")
    return out


def _caller(scope: dict, headers: dict[str, str]) -> str:
    xff = headers.get("x-forwarded-for", "")
    if xff:
        return xff.split(",")[0].strip()
    client = scope.get("client")
    return client[0] if client else ""


async def _capture_request_body(scope: dict, receive: Callable):
    """捕获请求体文本，并返回可重放的 receive（保证下游仍读到完整 body）。"""
    headers = _headers_dict(scope)
    if scope.get("method", "").upper() not in _BODY_METHODS:
        return "", receive
    if "multipart/form-data" in headers.get("content-type", ""):
        return "<multipart 请求体未记录>", receive
    try:
        length = int(headers.get("content-length") or 0)
    except ValueError:
        length = 0
    max_body = config.api_log.max_body
    if length > max_body:
        return f"<请求体过大未记录: {length} bytes>", receive

    messages: list[dict] = []
    raw = b""
    while True:
        msg = await receive()
        messages.append(msg)
        if msg["type"] != "http.request":
            break
        raw += msg.get("body", b"")
        if not msg.get("more_body", False):
            break
    idx = 0

    async def replay() -> dict:
        nonlocal idx
        if idx < len(messages):
            msg = messages[idx]
            idx += 1
            return msg
        return {"type": "http.disconnect"}

    text = raw[:max_body].decode("utf-8", "replace")
    if len(raw) > max_body:
        text += "...<截断>"
    return text, replay


class ApiLogMiddleware:
    """API 调用日志中间件（纯 ASGI）：请求/响应各打一条日志，合并落一行到 PostgreSQL（见 ApiLogDao）。"""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope.get("type") != "http" or not config.api_log.enabled:
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        if _excluded(path, config.api_log.exclude):
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "").upper()
        headers = _headers_dict(scope)
        caller = _caller(scope, headers)
        tid = headers.get("x-trace-id") or trace_id_ctx.get()
        query = scope.get("query_string", b"").decode("utf-8", "replace")
        req_at = datetime.now()
        # 默认不采集 body：省掉缓冲整个请求体的开销，也避免日志/表被大 body 撑爆
        save_body = config.api_log.save_body
        if save_body:
            req_body, receive = await _capture_request_body(scope, receive)
        else:
            req_body = ""

        logger.info(
            f"API 请求 trace={tid} {method} {path} caller={caller} "
            f"query={query} headers={_compact(headers)}"
            + (f" body={req_body}" if save_body else "")
        )

        status: dict[str, Any] = {}
        chunks: list[bytes] = []
        total = 0
        max_body = config.api_log.max_body

        async def send_wrapper(message: dict) -> None:
            nonlocal total
            if message["type"] == "http.response.start":
                status["code"] = message.get("status")
            elif message["type"] == "http.response.body" and save_body:
                chunk = message.get("body", b"")
                if total < max_body:
                    chunks.append(chunk)
                    total += len(chunk)
            await send(message)

        t0 = time.perf_counter()
        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            cost_ms = int((time.perf_counter() - t0) * 1000)
            resp_at = datetime.now()
            status_code = status.get("code")

            resp_body = ""
            if save_body:
                resp_body = b"".join(chunks)[:max_body].decode("utf-8", "replace")
                if total >= max_body:
                    resp_body += "...<截断>"

            user_id = get_user_id()
            tenant_id = get_tenant_id()
            logger.info(
                f"API 响应 trace={tid} {method} {path} status={status_code} "
                f"tenant={tenant_id or ''} user={user_id or ''} cost_ms={cost_ms}"
                + (f" body={resp_body}" if save_body else "")
            )

            if config.api_log.db:
                from backend.data.dao.ops.api_log_dao import ApiLogDao

                await ApiLogDao().save({
                    "trace_id": tid,
                    "caller": caller,
                    "user_id": user_id,
                    "tenant_id": tenant_id,
                    "method": method,
                    "path": path,
                    "route": getattr(scope.get("route"), "path", None),
                    "query_string": query,
                    "req_headers": headers,
                    "req_time": req_at,
                    "status_code": status_code,
                    "resp_time": resp_at,
                    "cost_ms": cost_ms,
                })
