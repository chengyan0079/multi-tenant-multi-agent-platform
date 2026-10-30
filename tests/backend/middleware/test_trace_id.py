"""TraceIdMiddleware 强制传播单测（不连 DB）。

验证规则：
- 任意接口缺 X-Trace-Id 都不再拒绝，后端生成并回写到响应头；
- 携带 X-Trace-Id 时后端原样使用（链路串联）；
- 同一请求内 contextvar 与回写响应头的 trace 一致（调用链共用一个）。
"""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from backend.common.logger import trace_id_ctx
from backend.middleware.trace_id import TraceIdMiddleware


def _app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(TraceIdMiddleware)

    @app.post("/api/v1/auth/login")
    async def login() -> dict:
        return {"ok": True}

    @app.get("/dashboard")
    async def dash(request: Request) -> dict:
        return {"trace": trace_id_ctx.get(), "header": request.headers.get("X-Trace-Id")}

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    return app


def test_business_missing_trace_generated_and_echoed() -> None:
    client = TestClient(_app())
    r = client.get("/dashboard")
    assert r.status_code == 200
    # 业务接口缺 X-Trace-Id 不再拒绝，后端生成并回写到响应头
    assert "X-Trace-Id" in r.headers
    assert r.headers["X-Trace-Id"]
    # 同一请求内 contextvar 与回写响应头的 trace 一致（调用链共用一个）
    assert r.json()["trace"] == r.headers["X-Trace-Id"]
    assert r.json()["header"] is None


def test_login_missing_trace_generated_and_echoed() -> None:
    client = TestClient(_app())
    r = client.post("/api/v1/auth/login")
    assert r.status_code == 200
    # 后端生成并回写到响应头
    assert "X-Trace-Id" in r.headers
    assert r.headers["X-Trace-Id"]


def test_health_exempt_missing_trace_ok() -> None:
    client = TestClient(_app())
    r = client.get("/health")
    assert r.status_code == 200


def test_non_login_with_trace_uses_header_not_regenerated() -> None:
    client = TestClient(_app())
    r = client.get("/dashboard", headers={"X-Trace-Id": "abc123"})
    assert r.status_code == 200
    # 后端原样使用请求头里的 trace，不重新生成
    assert r.json()["trace"] == "abc123"
    assert r.json()["header"] == "abc123"
