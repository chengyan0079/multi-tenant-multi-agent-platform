"""超管菜单管理 / 角色写操作端点集成测试（AsyncMock 替 DAO，不连真实库）。

复用 test_endpoints 的鉴权 fixture 思路：patch 掉 DAO 与 RBAC 解析，仅校验路由装配、
require_super_admin / require_scope 在链路上的生效，以及内置角色禁删等守卫。
"""
from __future__ import annotations

import jwt
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.exceptions import register_exception_handlers
from backend.api.router import api_router
from backend.app_state import app_state
from backend.data.dao.ops.audit_dao import AuditDao
from backend.data.dao.auth.menu_dao import MenuDao
from backend.data.dao.auth.rbac_dao import RbacDao
from backend.data.dao.auth.user_dao import UserDao
from backend.observability.exception import BizException, ErrCode

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


_SA_SCOPES = [
    "tenant:page", "tenant:update",
    "rbac:page", "rbac:add", "rbac:update", "rbac:delete",
    "user:page",
    "audit:page",
    "menu:page", "menu:add", "menu:update", "menu:delete",
    "dashboard:view",
]
_SA_IDENTITY = {"role_name": "admin", "scopes": _SA_SCOPES}
_SA_USER = {"id": 1001, "username": "admin", "name": "admin", "tenant_id": 1, "enabled": True}


@pytest.fixture
def client():
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
        "backend.data.dao.auth.tenant_dao.TenantDao.list_with_stats", new=AsyncMock(return_value=[])
    ), patch(
        "backend.data.dao.auth.menu_dao.MenuDao.list_all",
        new=AsyncMock(return_value=[
            {"id": 1, "name": "租户管理", "path": "/tenants", "icon": "", "parent_id": 0,
             "sort_order": 1, "visible": True, "scope": "tenant:read"}
        ]),
    ), patch(
        "backend.data.dao.auth.menu_dao.MenuDao.build_tree",
        new=MagicMock(return_value=[{"id": 1, "name": "租户管理", "children": []}]),
    ), patch(
        "backend.data.dao.auth.menu_dao.MenuDao.create", new=AsyncMock(return_value=99)
    ), patch(
        "backend.data.dao.auth.menu_dao.MenuDao.update", new=AsyncMock(return_value=1)
    ), patch(
        "backend.data.dao.auth.menu_dao.MenuDao.delete", new=AsyncMock(return_value=1)
    ), patch(
        "backend.data.dao.auth.rbac_dao.RbacDao.next_role_id", new=AsyncMock(return_value=10)
    ), patch(
        "backend.data.dao.auth.rbac_dao.RbacDao.create_role", new=AsyncMock(return_value=10)
    ), patch(
        "backend.data.dao.auth.rbac_dao.RbacDao.delete_role", new=AsyncMock(return_value=None)
    ), patch(
        "backend.data.dao.ops.audit_dao.AuditDao.write", new=AsyncMock(return_value=None)
    ):
        app = FastAPI()
        app.include_router(api_router)
        register_exception_handlers(app)
        yield TestClient(app)


def _login(c: TestClient) -> str:
    return c.post("/api/v1/auth/login", json={"username": "admin", "password": "123456"}).json()["data"]["token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_menu_tree_requires_auth(client):
    assert client.get("/api/v1/admin/menus").status_code == 401


def test_menu_tree_list(client):
    token = _login(client)
    resp = client.get("/api/v1/admin/menus", headers=_auth(token))
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["total"] == 1
    assert data["items"][0]["name"] == "租户管理"


def test_menu_create(client):
    token = _login(client)
    resp = client.post(
        "/api/v1/admin/menus",
        headers=_auth(token),
        json={"name": "新菜单", "path": "/new", "icon": "AppOutlined", "parent_id": 0,
              "sort_order": 9, "visible": True, "scope": "rbac:page"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["id"] == 99


def test_menu_update_self_parent_rejected(client):
    token = _login(client)
    resp = client.put(
        "/api/v1/admin/menus/5",
        headers=_auth(token),
        json={"name": "x", "path": "/x", "icon": "", "parent_id": 5,
              "sort_order": 0, "visible": True, "scope": None},
    )
    assert resp.status_code == 200
    assert resp.json()["code"] == ErrCode.PARAM_ERROR


def test_menu_delete(client):
    token = _login(client)
    resp = client.delete("/api/v1/admin/menus/5", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json()["data"]["id"] == 5


def test_role_create(client):
    token = _login(client)
    resp = client.post(
        "/api/v1/admin/roles",
        headers=_auth(token),
        json={"name": "custom", "description": "自定义", "scopes": ["qa:page"]},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["role_id"] == 10


def test_role_delete_ok(client):
    token = _login(client)
    resp = client.delete("/api/v1/admin/roles/10", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json()["data"]["role_id"] == 10


def test_role_delete_builtin_rejected(client):
    token = _login(client)
    # 模拟 DAO 守卫：内置角色（1/2/3/5）抛 PARAM_ERROR
    with patch(
        "backend.data.dao.auth.rbac_dao.RbacDao.delete_role",
        new=AsyncMock(side_effect=BizException(ErrCode.PARAM_ERROR, "内置角色不可删除")),
    ):
        resp = client.delete("/api/v1/admin/roles/2", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json()["code"] == ErrCode.PARAM_ERROR


def test_menu_write_requires_rbac_write(client):
    token = _login(client)
    # 把身份降级为只有 rbac:read，写操作应 403
    read_only = dict(_SA_IDENTITY, scopes=["rbac:page"])
    with patch(
        "backend.data.dao.auth.rbac_dao.RbacDao.get_super_admin_identity",
        new=AsyncMock(return_value=read_only),
    ):
        resp = client.post(
            "/api/v1/admin/menus",
            headers=_auth(token),
            json={"name": "x", "path": "/x", "icon": "", "parent_id": 0,
                  "sort_order": 0, "visible": True, "scope": None},
        )
    # 缺 rbac:write 时 require_scope 抛 TenantError(AgentError)，按约定返回 200 + code=FORBIDDEN
    assert resp.status_code == 200
    assert resp.json()["code"] == ErrCode.FORBIDDEN
