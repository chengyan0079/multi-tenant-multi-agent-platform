"""
api_log - API 调用日志中间件（纯 ASGI）

记录每次 API 调用的调用方 / 请求头 / 方法 / 路由 / 状态 / 耗时，
"请求"与"响应"各打一条日志（便于按时间线排障），并合并落一行到 agent_api_call_log。
x-trace-id 的强制传播与生成由外层 TraceIdMiddleware 负责：登录接口（获取 token）允许为空
（后端生成），其余接口必须携带 x-trace-id（来自同一操作链上游），缺失即拒绝（400）且不重新
生成；本中间件仅读取 TraceIdMiddleware 已确定的 trace_id 写日志。
请求参数默认就记录：GET/DELETE 解析 query 为结构化 params 打印，POST/PUT/PATCH 取 body，
两者敏感字段（password/token/secret...）均脱敏为 ***，
避免明文凭据落到 DEBUG 日志（需 LOG_LEVEL=DEBUG 才打印）；body 仅对 POST/PUT/PATCH 且长度可控者捕获并重放给下游，
multipart 与超大体不消费、不记录。
响应体受 `API_LOG_SAVE_BODY` 控制（默认不记录，开启时按上限截断、同样脱敏）。
实现要点（不用 BaseHTTPMiddleware，纯 ASGI 不吃大文件）：
  - 敏感头（authorization/cookie/...）与敏感 body 字段均脱敏为 ***。
"""
from __future__ import annotations

import json
import time
from datetime import datetime
from typing import Any, Callable
from urllib.parse import parse_qsl

from starlette.requests import Request

from backend.app_state import app_state, get_tenant_id, get_user_id, trace_id_ctx
from backend.config import config
from backend.common.logger import ensure_trace_id, logger

_SENSITIVE_HEADERS = frozenset({
    "authorization", "cookie", "set-cookie", "proxy-authorization", "x-api-key",
    "x-auth-signature",
})
_BODY_METHODS = frozenset({"POST", "PUT", "PATCH"})

# 请求/响应体里需脱敏的字段（避免明文密码/token/secret 落到 DEBUG 日志）
_SENSITIVE_BODY_KEYS = frozenset({
    "password", "pwd", "passwd", "old_password", "new_password",
    "token", "access_token", "refresh_token", "secret", "api_key",
    "authorization", "auth_sign", "code", "captcha",
})


def _safe_json(text: str) -> Any:
    """尽量把 body 文本解析成对象；失败（非 JSON / form）原样返回。"""
    text = text.strip()
    if not text:
        return text
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return text


def _mask_body(data: Any) -> Any:
    """递归把敏感字段值替换成 ***（仅对解析后的 dict/list 生效）。"""
    if isinstance(data, dict):
        return {
            k: ("***" if k.lower() in _SENSITIVE_BODY_KEYS else _mask_body(v))
            for k, v in data.items()
        }
    if isinstance(data, list):
        return [_mask_body(v) for v in data]
    return data


def _excluded(path: str, prefixes: list[str] | None) -> bool:
    return any(path.startswith(p) for p in (prefixes or []))


def _full_route(path: str, pattern: str | None) -> str | None:
    """把路由模板补成完整 API 路径。

    include_router 的 prefix（如 /api/v1/admin）不一定体现在 scope["route"].path 中，
    这里用实际请求路径按段对齐补齐前缀；模板已含前缀时保持原样。
    """
    if not pattern:
        return pattern
    req_segments = [s for s in path.split("/") if s]
    tpl_segments = [s for s in pattern.split("/") if s]
    if not tpl_segments or len(tpl_segments) > len(req_segments):
        return pattern
    prefix = req_segments[: len(req_segments) - len(tpl_segments)]
    return "/" + "/".join(prefix + tpl_segments)


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
        # trace_id 由外层 TraceIdMiddleware 注入（含强制传播与豁免）；此处直接取，
        # 未注入时兜底生成（仅当 TraceIdMiddleware 未装配，正常不应触发）。
        tid = trace_id_ctx.get() or ensure_trace_id()
        query = scope.get("query_string", b"").decode("utf-8", "replace")
        req_at = datetime.now()
        # 请求参数默认记录，敏感字段脱敏：
        # - POST/PUT/PATCH 取 body（JSON 解析后结构化）；
        # - GET 等无 body，解析 query_string 为 dict 结构化打印（同样脱敏）。
        # 统一用 params= 字段，GET/POST 都有清晰的请求参数。
        save_body = config.api_log.save_body
        req_body, receive = await _capture_request_body(scope, receive)
        req_params = _compact(_mask_body(_safe_json(req_body))) if req_body else ""
        if not req_params and query:
            qd = dict(parse_qsl(query))
            req_params = _compact(_mask_body(qd)) if qd else ""

        logger.debug(
            f"API 请求 trace={tid} {method} {path} caller={caller} "
            f"headers={_compact(headers)}"
            + (f" params={req_params}" if req_params else "")
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
                raw_resp = b"".join(chunks)[:max_body].decode("utf-8", "replace")
                if total >= max_body:
                    raw_resp += "...<截断>"
                resp_body = _compact(_mask_body(_safe_json(raw_resp)))

            user_id = get_user_id()
            tenant_id = get_tenant_id()
            logger.debug(
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
                    "route": _full_route(path, getattr(scope.get("route"), "path", None)),
                    "query_string": query,
                    "req_headers": headers,
                    "req_time": req_at,
                    "status_code": status_code,
                    "resp_time": resp_at,
                    "cost_ms": cost_ms,
                })
