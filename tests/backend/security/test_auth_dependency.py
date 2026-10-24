"""身份依赖测试：require_super_admin / require_tenant_admin 只读 request.state。

以及 get_current_user 把身份快照写入 state 的行为。
"""
import pytest
from fastapi import HTTPException
from starlette.requests import Request

from backend.app_state import app_state
from backend.middleware import auth as auth_module
from backend.middleware.auth import get_current_user
from backend.observability.exception import TenantError
from backend.security.rbac import Identity
from backend.security.security import require_super_admin, require_tenant_admin


def _request(headers: dict[str, str] | None = None, **state: object) -> Request:
    """构造最小 Request，可预置 state 与 header。"""
    raw_headers = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    request = Request(
        {"type": "http", "method": "GET", "path": "/", "headers": raw_headers}
    )
    for key, value in state.items():
        setattr(request.state, key, value)
    return request


async def test_require_super_admin_accepts_flag() -> None:
    """state 上是超管就放行。"""
    await require_super_admin()(_request(is_super_admin=True))


async def test_require_super_admin_rejects_others() -> None:
    """没有标记或标记为假都拒绝。"""
    with pytest.raises(TenantError):
        await require_super_admin()(_request())
    with pytest.raises(TenantError):
        await require_super_admin()(_request(is_super_admin=False))


async def test_require_tenant_admin_accepts_flag() -> None:
    """state 上是租户管理员就放行。"""
    await require_tenant_admin()(_request(is_tenant_admin=True))


async def test_require_tenant_admin_rejects_super_admin() -> None:
    """超管不自动通过：普通用户的维护入口只给租户管理员。"""
    with pytest.raises(TenantError):
        await require_tenant_admin()(_request(is_super_admin=True))
    with pytest.raises(TenantError):
        await require_tenant_admin()(_request())


@pytest.fixture
def trust_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    """强制走 header 身份，避免 .env 里的开发兜底用户干扰。"""
    security = app_state.settings.security
    monkeypatch.setattr(security, "trust_headers", True)
    monkeypatch.setattr(security, "dev_user_id", "")
    monkeypatch.setattr(security, "dev_tenant_id", "")


async def test_get_current_user_writes_identity(
    monkeypatch: pytest.MonkeyPatch, trust_headers: None
) -> None:
    """身份解析后，角色名与两个布尔量都要落到 request.state。"""

    async def fake_resolve(user_id: int, tenant_id: int | None) -> Identity:
        return Identity(user_id, tenant_id, "admin", True, ["*"])

    monkeypatch.setattr(
        auth_module.RbacService, "resolve_identity", staticmethod(fake_resolve)
    )
    request = _request({"X-User-Id": "1001", "X-Tenant-Id": "100"})

    current = await get_current_user(request)

    assert current.role_name == "admin"
    assert current.is_super_admin is True
    assert current.is_tenant_admin is False
    assert current.roles == ["admin"]
    assert request.state.role_name == "admin"
    assert request.state.roles == ["admin"]
    assert request.state.is_super_admin is True
    assert request.state.is_tenant_admin is False
    assert request.state.scopes == ["*"]


async def test_get_current_user_without_allocation(
    monkeypatch: pytest.MonkeyPatch, trust_headers: None
) -> None:
    """解析不到身份（无分配或租户停用）返回 403。"""

    async def fake_resolve(user_id: int, tenant_id: int | None) -> None:
        return None

    monkeypatch.setattr(
        auth_module.RbacService, "resolve_identity", staticmethod(fake_resolve)
    )
    request = _request({"X-User-Id": "2002", "X-Tenant-Id": "200"})

    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(request)

    assert exc_info.value.status_code == 403
    assert "2002" in str(exc_info.value.detail)
