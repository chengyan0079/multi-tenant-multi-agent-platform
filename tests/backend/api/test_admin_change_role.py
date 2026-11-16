"""改用户角色端点分流测试（AsyncMock 替 DAO，不连真实库）。

覆盖：平台超管只能任命为租户管理员（可跨租户），租户管理员只能分配普通角色。
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
from backend.data.dao.auth.rbac_dao import RbacDao
from backend.data.dao.auth.tenant_dao import TenantDao
from backend.data.dao.auth.user_dao import UserDao
from backend.observability.exception import ErrCode

_SECRET = "test-secret"

_SA_SCOPES = ["user:page", "user:update", "user:view", "user:add"]
_SA_USER = {"id": 1001, "username": "admin", "name": "admin", "tenant_id": None, "enabled": True}
_TA_USER = {"id": 2001, "username": "ta", "name": "ta", "tenant_id": 1, "enabled": True}


class _FakeSecurity:
    jwt_secret = _SECRET
    jwt_algorithm = "HS256"
    jwt_expire_minutes = 1440


def _token(user_id: int, tenant_id: int | None = None) -> str:
    payload: dict = {"user_id": user_id}
    if tenant_id is not None:
        payload["tenant_id"] = tenant_id
    return "Bearer " + jwt.encode(payload, _SECRET, algorithm="HS256")


def _auth(token: str) -> dict:
    return {"Authorization": token}


@pytest.fixture
def client():
    with patch.object(app_state.settings, "security", _FakeSecurity()), patch(
        "backend.data.dao.auth.user_dao.UserDao.authenticate",
        new=AsyncMock(return_value=_SA_USER),
    ), patch(
        "backend.data.dao.auth.user_dao.UserDao.get",
        new=AsyncMock(return_value=_SA_USER),
    ), patch(
        "backend.data.dao.auth.rbac_dao.RbacDao.get_super_admin_identity",
        new=AsyncMock(return_value={"role_name": "admin", "scopes": _SA_SCOPES}),
    ), patch(
        "backend.data.dao.auth.rbac_dao.RbacDao.get_user_assignments",
        new=AsyncMock(return_value=[]),
    ), patch(
        "backend.data.dao.ops.audit_dao.AuditDao.write",
        new=AsyncMock(return_value=None),
    ):
        app = FastAPI()
        app.include_router(api_router)
        register_exception_handlers(app)
        yield TestClient(app)


def _patch_user(target: dict) -> patch:
    return patch.object(UserDao, "get", new=AsyncMock(return_value=target))


# ---- 平台超管 ----

def test_super_admin_assign_tenant_admin_ok(client):
    token = _auth(_token(1001))
    with _patch_user({"id": 5, "tenant_id": 1, "is_super_admin": False, "enabled": True}), patch.object(
        RbacDao, "get_role_id", new=AsyncMock(return_value=5)
    ), patch.object(TenantDao, "get", new=AsyncMock(return_value={"id": 1})), patch.object(
        RbacDao, "set_tenant_admin", new=AsyncMock(return_value=None)
    ):
        resp = client.put(
            "/api/v1/admin/rbac/users/5/role",
            headers=token,
            json={"tenant_id": 1, "role": "tenant_admin"},
        )
    assert resp.status_code == 200
    assert resp.json()["data"]["role"] == "tenant_admin"


def test_super_admin_assign_student_rejected(client):
    token = _auth(_token(1001))
    with _patch_user({"id": 5, "tenant_id": 1, "is_super_admin": False, "enabled": True}), patch.object(
        RbacDao, "get_role_id", new=AsyncMock(return_value=3)
    ):
        resp = client.put(
            "/api/v1/admin/rbac/users/5/role",
            headers=token,
            json={"tenant_id": 1, "role": "student"},
        )
    assert resp.status_code == 200
    assert resp.json()["code"] == ErrCode.PARAM_ERROR


def test_super_admin_cross_tenant_ok(client):
    token = _auth(_token(1001))
    # 目标用户本属租户 2，超管仍可任命为租户 1 的管理员
    with _patch_user({"id": 5, "tenant_id": 2, "is_super_admin": False, "enabled": True}), patch.object(
        RbacDao, "get_role_id", new=AsyncMock(return_value=5)
    ), patch.object(TenantDao, "get", new=AsyncMock(return_value={"id": 1})), patch.object(
        RbacDao, "set_tenant_admin", new=AsyncMock(return_value=None)
    ):
        resp = client.put(
            "/api/v1/admin/rbac/users/5/role",
            headers=token,
            json={"tenant_id": 1, "role": "tenant_admin"},
        )
    assert resp.status_code == 200
    assert resp.json()["data"]["role"] == "tenant_admin"


# ---- 租户管理员 ----

def test_tenant_admin_assign_tenant_admin_rejected(client):
    token = _auth(_token(2001, tenant_id=1))
    with _patch_user({"id": 5, "tenant_id": 1, "is_super_admin": False, "enabled": True}), patch.object(
        RbacDao, "get_identity",
        new=AsyncMock(return_value={"role_name": "tenant_admin", "scopes": ["user:update"]}),
    ), patch.object(
        RbacDao, "list_roles_with_permissions",
        new=AsyncMock(return_value=[{"name": "student"}, {"name": "teacher"}]),
    ):
        resp = client.put(
            "/api/v1/admin/rbac/users/5/role",
            headers=token,
            json={"tenant_id": 1, "role": "tenant_admin"},
        )
    assert resp.json()["code"] == ErrCode.PARAM_ERROR


def test_tenant_admin_assign_student_ok(client):
    token = _auth(_token(2001, tenant_id=1))
    with _patch_user({"id": 5, "tenant_id": 1, "is_super_admin": False, "enabled": True}), patch.object(
        RbacDao, "get_identity",
        new=AsyncMock(return_value={"role_name": "tenant_admin", "scopes": ["user:update"]}),
    ), patch.object(
        RbacDao, "list_roles_with_permissions",
        new=AsyncMock(return_value=[{"name": "student"}, {"name": "teacher"}]),
    ), patch.object(RbacDao, "get_role_id", new=AsyncMock(return_value=3)), patch.object(
        TenantDao, "get", new=AsyncMock(return_value={"id": 1})
    ), patch.object(RbacDao, "assign_role", new=AsyncMock(return_value=None)):
        resp = client.put(
            "/api/v1/admin/rbac/users/5/role",
            headers=token,
            json={"tenant_id": 1, "role": "student"},
        )
    assert resp.status_code == 200
    assert resp.json()["data"]["role"] == "student"
