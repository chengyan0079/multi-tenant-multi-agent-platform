"""RbacService 与 RbacDao 之间的衔接：不连库，只验证参数与返回值转换。

DAO 的 SQL 本身由 `tests/backend/data/test_sql_audit.py` 做列名对齐校验，
这里补的是「服务层怎么调 DAO、DAO 的行怎么变成 Identity」。
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

from backend.data.dao.auth.rbac_dao import RbacDao
from backend.security.rbac import RbacService


async def test_resolve_identity_maps_row_to_identity() -> None:
    """库行转 Identity：角色名与 scopes 原样透传，租户即查询用的 tenant_id。"""
    row = {"role_name": "tenant_admin", "scopes": ["qa:ask"]}
    with patch.object(RbacDao, "get_identity", new=AsyncMock(return_value=row)):
        identity = await RbacService.resolve_identity(2001, 200)

    assert identity is not None
    assert identity.user_id == 2001
    assert identity.tenant_id == 200
    assert identity.role_name == "tenant_admin"
    assert identity.is_super_admin is False
    assert identity.scopes == ["qa:ask"]


async def test_resolve_identity_returns_none_when_missing() -> None:
    """分配不存在 / 角色缺失 / 租户停用，统一按无身份处理。"""
    with patch.object(RbacDao, "get_identity", new=AsyncMock(return_value=None)):
        assert await RbacService.resolve_identity(2001, 200) is None


async def test_resolve_identity_skips_query_without_tenant() -> None:
    """没有租户上下文时直接返回 None，不查库。"""
    mock = AsyncMock()
    with patch.object(RbacDao, "get_identity", new=mock):
        assert await RbacService.resolve_identity(2001, None) is None
    mock.assert_not_awaited()
