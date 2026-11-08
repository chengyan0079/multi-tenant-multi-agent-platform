"""鉴权接口集成测试：用 TestClient 真实跑通 login→menus→me，并校验超管/租户守卫。

不连真实 DB：DAO 与 RBAC 解析全部用 AsyncMock 替换，仅验证路由装配、token 单源、
require_scope/require_super_admin/require_tenant 在请求链路上的实际生效。

patch 必须覆盖整个请求过程（用 fixture 的 with 上下文包住 TestClient 的使用），
否则函数返回后 patch 即撤销，真实 DAO 会去拿 postgres 客户端而报错。
"""
from __future__ import annotations

import jwt
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.exceptions import register_exception_handlers
from backend.api.router import api_router
from backend.app_state import app_state
from backend.observability.exception import ErrCode

_SECRET = "test-secret"


class _FakeSecurity:
    jwt_secret = _SECRET
    jwt_algorithm = "HS256"
    jwt_expire_minutes = 1440


def _token(user_id: int, tenant_id: int | None = None) -> str:
    payload: dict = {"user_id": user_id}
    if tenant_id is not None:
        payload["tenant_id"] = tenant_id
    return "Bearer " + jwt.encode(payload, _SECRET, algorithm="HS256")


_SA_SCOPES = ["tenant:page", "tenant:update", "rbac:page", "rbac:update", "user:page", "audit:page"]
_SA_IDENTITY = {"role_name": "admin", "scopes": _SA_SCOPES}
_SA_USER = {"id": 1001, "username": "admin", "name": "admin", "tenant_id": 1, "enabled": True}


@pytest.fixture
def client():
    """patch 在 fixture 生命周期内持续生效，覆盖 TestClient 的请求调用。"""
    with patch.object(app_state.settings, "security", _FakeSecurity()), patch(
        "backend.data.dao.auth.user_dao.UserDao.authenticate", new=AsyncMock(return_value=_SA_USER)
    ), patch(
        "backend.data.dao.auth.user_dao.UserDao.get", new=AsyncMock(return_value=_SA_USER)
    ), patch(
        "backend.data.dao.auth.rbac_dao.RbacDao.get_super_admin_identity",
        new=AsyncMock(return_value=_SA_IDENTITY),
    ), patch(
        "backend.data.dao.auth.rbac_dao.RbacDao.get_user_assignments", new=AsyncMock(return_value=[])
    ), patch(
        "backend.data.dao.auth.menu_dao.MenuDao.build",
        new=AsyncMock(return_value=[{"id": 1, "name": "租户管理", "path": "/tenants", "children": []}]),
    ), patch(
        "backend.data.dao.auth.tenant_dao.TenantDao.list_with_stats", new=AsyncMock(return_value=([], 0))
    ):
        app = FastAPI()
        app.include_router(api_router)
        register_exception_handlers(app)
        yield TestClient(app)


def _login(client: TestClient) -> str:
    return client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "123456"}
    ).json()["data"]["token"]


def test_login_returns_token_menus_scopes(client):
    resp = client.post("/api/v1/auth/login", json={"username": "admin", "password": "123456"})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["token"]
    assert data["is_super_admin"] is True
    assert data["current_tenant"] is None
    assert data["scopes"] == _SA_SCOPES
    assert data["menus"][0]["path"] == "/tenants"


def test_menus_requires_auth(client):
    # 无 token：认证守卫直接 401
    assert client.get("/api/v1/auth/menus").status_code in (401, 403)


def test_menus_with_token(client):
    token = _login(client)
    resp = client.get("/api/v1/auth/menus", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["data"]["menus"][0]["path"] == "/tenants"


def test_me_with_token(client):
    token = _login(client)
    resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["is_super_admin"] is True
    assert body["tenant_id"] is None
    assert body["scopes"] == _SA_SCOPES


def test_admin_tenants_requires_auth(client):
    assert client.get("/api/v1/admin/tenants").status_code == 401


def test_admin_tenants_super_admin_ok(client):
    token = _login(client)
    resp = client.get("/api/v1/admin/tenants", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["data"]["total"] == 0


def test_super_admin_blocked_from_tenant_business(client):
    """设计不变式：超管无租户，调业务接口 /api/v1/tenant/* 一律 403。"""
    token = _login(client)
    resp = client.get("/api/v1/tenant/users", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


def test_login_wrong_password_401(client):
    """登录凭证错误应走 AuthError → 401 + code=UNAUTHORIZED。"""
    with patch(
        "backend.data.dao.auth.user_dao.UserDao.authenticate", new=AsyncMock(return_value=None)
    ):
        resp = client.post(
            "/api/v1/auth/login", json={"username": "admin", "password": "wrong"}
        )
    assert resp.status_code == 401
    assert resp.json()["code"] == ErrCode.UNAUTHORIZED
