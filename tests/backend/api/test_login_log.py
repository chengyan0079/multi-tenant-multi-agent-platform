"""登录日志测试：/login 每次调用写一行 agent_login_log（成功与失败都要）。

不连 DB：替换 _login 与 LoginLogDao.write，只验证写入参数与旁路特性。
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.exceptions import register_exception_handlers
from backend.api.router import api_router
from backend.observability.exception import AuthError

_WRITE = "backend.api.v1.auth.router.LoginLogDao.write"
_LOGIN = "backend.api.v1.auth.router._login"

_CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(api_router)
    register_exception_handlers(app)
    return app


def _post(**headers):
    return TestClient(_app()).post(
        "/api/v1/auth/login",
        json={"username": "alice", "password": "pw"},
        headers={"user-agent": _CHROME_UA, **headers},
    )


def test_login_success_records_log():
    _login = AsyncMock(return_value={
        "token": "t",
        "user": {"user_id": 7, "username": "alice"},
        "current_tenant": {"id": 2, "name": "租户二"},
        "permissions": [],
        "menus": [],
    })
    with patch(_LOGIN, new=_login), patch(_WRITE, new=AsyncMock()) as write:
        resp = _post(**{"x-forwarded-for": "203.0.113.9, 10.0.0.1"})

    assert resp.status_code == 200
    kwargs = write.await_args.kwargs
    assert kwargs["success"] is True
    assert (kwargs["user_id"], kwargs["tenant_id"]) == (7, 2)
    assert kwargs["username"] == "alice"
    # 反向代理后取 X-Forwarded-For 首段，而不是代理地址
    assert kwargs["ip"] == "203.0.113.9"
    assert kwargs["client"] == "Chrome / Windows"


def test_login_failure_still_records_log():
    """密码错也要留痕：user_id 为空，但保留尝试的用户名与失败原因。"""
    with patch(_LOGIN, new=AsyncMock(side_effect=AuthError("用户名或密码错误"))), patch(
        _WRITE, new=AsyncMock()
    ) as write:
        resp = _post()

    assert resp.status_code == 401
    kwargs = write.await_args.kwargs
    assert kwargs["success"] is False
    assert kwargs["user_id"] is None
    assert kwargs["username"] == "alice"
    assert kwargs["fail_reason"] == "用户名或密码错误"


def test_login_not_broken_when_log_write_fails():
    """登录日志是旁路：写失败只告警，登录结果不受影响。"""
    _login = AsyncMock(return_value={
        "token": "t",
        "user": {"user_id": 7, "username": "alice"},
        "current_tenant": None,
        "permissions": [],
        "menus": [],
    })
    with patch(_LOGIN, new=_login), patch(
        _WRITE, new=AsyncMock(side_effect=RuntimeError("db down"))
    ):
        resp = _post()

    assert resp.status_code == 200
    assert resp.json()["data"]["token"] == "t"
