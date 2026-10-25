"""鉴权核心单测：token 单源 + 超管/租户分支（见 docs/登录与权限校验说明.md §4）。

不走真实 DB：DAO 层用 AsyncMock 替换，验证 get_current_user 的分支选择与上下文写入。
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import jwt
import pytest
from fastapi import HTTPException, Request

from backend.app_state import app_state
from backend.middleware.auth import get_current_user


class _FakeSecurity:
    jwt_secret = "test-secret"
    jwt_algorithm = "HS256"
    jwt_expire_minutes = 1440


def _token(user_id: int, tenant_id: int | None = None) -> str:
    payload = {"user_id": user_id}
    if tenant_id is not None:
        payload["tenant_id"] = tenant_id
    return "Bearer " + jwt.encode(payload, "test-secret", algorithm="HS256")


def _make_request(token: str) -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/x",
        "headers": [(b"authorization", token.encode())],
    }
    return Request(scope)


@pytest.fixture
def sec():
    with patch.object(app_state.settings, "security", _FakeSecurity()):
        yield


@pytest.mark.asyncio
async def test_super_admin_branch(sec):
    sa = {"role_name": "admin", "tenant_is_primary": True, "scopes": ["agent:read"]}
    with patch(
        "backend.data.dao.auth.rbac_dao.RbacDao.get_super_admin_identity",
        new=AsyncMock(return_value=sa),
    ), patch(
        "backend.middleware.auth.UserDao.get",
        new=AsyncMock(return_value={"tenant_id": 100}),
    ):
        user = await get_current_user(_make_request(_token(1001)))
    assert user.is_super_admin is True
    assert user.tenant_id is None
    assert user.home_tenant_id == 100
    assert user.scopes == ["agent:read"]  # 超管用种子里 admin 角色的具体权限点，不再用 "*"
    assert user.is_tenant_admin is False


@pytest.mark.asyncio
async def test_tenant_branch(sec):
    tenant = {"role_name": "tenant_admin", "tenant_is_primary": False, "scopes": ["rbac:read"]}
    with patch(
        "backend.data.dao.auth.rbac_dao.RbacDao.get_identity",
        new=AsyncMock(return_value=tenant),
    ), patch(
        "backend.middleware.auth.UserDao.get",
        new=AsyncMock(return_value={"tenant_id": 200}),
    ):
        user = await get_current_user(_make_request(_token(7, 200)))
    assert user.is_tenant_admin is True
    assert user.tenant_id == 200
    assert user.is_super_admin is False
    assert user.scopes == ["rbac:read"]


@pytest.mark.asyncio
async def test_non_super_admin_without_tenant_403(sec):
    with patch(
        "backend.data.dao.auth.rbac_dao.RbacDao.get_super_admin_identity",
        new=AsyncMock(return_value=None),
    ), patch(
        "backend.middleware.auth.UserDao.get",
        new=AsyncMock(return_value={"tenant_id": 100}),
    ):
        with pytest.raises(HTTPException) as exc:
            await get_current_user(_make_request(_token(7)))
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_missing_auth_401(sec):
    with pytest.raises(HTTPException) as exc:
        await get_current_user(_make_request(""))
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_invalid_token_403(sec):
    with pytest.raises(HTTPException) as exc:
        await get_current_user(_make_request("Bearer not-a-jwt"))
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_user_not_found_403(sec):
    sa = {"role_name": "admin", "tenant_is_primary": True, "scopes": ["agent:read"]}
    with patch(
        "backend.data.dao.auth.rbac_dao.RbacDao.get_super_admin_identity",
        new=AsyncMock(return_value=sa),
    ), patch(
        "backend.middleware.auth.UserDao.get",
        new=AsyncMock(return_value=None),
    ):
        with pytest.raises(HTTPException) as exc:
            await get_current_user(_make_request(_token(1001)))
    assert exc.value.status_code == 403
