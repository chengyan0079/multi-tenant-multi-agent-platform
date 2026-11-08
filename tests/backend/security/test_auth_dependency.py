"""身份依赖测试：require_super_admin / require_tenant / require_tenant_admin 只做布尔量判定。

get_current_user 已改为 token 单源（见 middleware/auth.py），其分支逻辑由 test_auth_core.py 覆盖。
本文件直接注入 CurrentUser（绕过 JWT/DB），只验证三个守卫对 is_super_admin / tenant_id /
is_tenant_admin 的判定，以及「超管进业务接口一律 403」。
"""
import pytest
from fastapi import HTTPException

from backend.middleware.auth import CurrentUser
from backend.security.security import (
    require_super_admin,
    require_tenant,
    require_tenant_admin,
)


def _current(
    *,
    is_super_admin: bool = False,
    is_tenant_admin: bool = False,
    tenant_id: int | None = 100,
) -> CurrentUser:
    return CurrentUser(
        user_id=1,
        tenant_id=tenant_id,
        home_tenant_id=tenant_id,
        role_name="admin" if (is_super_admin or is_tenant_admin) else "student",
        is_super_admin=is_super_admin,
        is_tenant_admin=is_tenant_admin,
        scopes=["qa:ask"],
    )


async def test_require_super_admin_accepts_flag() -> None:
    await require_super_admin()(current=_current(is_super_admin=True))


async def test_require_super_admin_rejects_others() -> None:
    with pytest.raises(HTTPException) as exc:
        await require_super_admin()(current=_current(is_super_admin=False))
    assert exc.value.status_code == 403
    assert "仅平台管理员" in str(exc.value.detail)


async def test_require_tenant_accepts_tenant_user() -> None:
    await require_tenant()(current=_current(tenant_id=200))


async def test_require_tenant_rejects_super_admin() -> None:
    with pytest.raises(HTTPException) as exc:
        await require_tenant()(current=_current(is_super_admin=True, tenant_id=None))
    assert exc.value.status_code == 403
    assert "无租户" in str(exc.value.detail)


async def test_require_tenant_admin_accepts_flag() -> None:
    await require_tenant_admin()(current=_current(is_tenant_admin=True))


async def test_require_tenant_admin_rejects_super_admin() -> None:
    with pytest.raises(HTTPException) as exc:
        await require_tenant_admin()(current=_current(is_super_admin=True))
    assert exc.value.status_code == 403
    assert "仅本租户管理员" in str(exc.value.detail)


async def test_require_tenant_admin_rejects_plain_user() -> None:
    with pytest.raises(HTTPException) as exc:
        await require_tenant_admin()(current=_current())
    assert exc.value.status_code == 403
    assert "仅本租户管理员" in str(exc.value.detail)
