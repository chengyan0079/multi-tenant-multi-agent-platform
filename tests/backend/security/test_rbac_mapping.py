"""RbacService 与 RbacDao 之间的衔接：不连库，只验证参数与返回值转换。

DAO 的 SQL 本身由 `tests/backend/data/test_sql_audit.py` 做列名对齐校验，
这里补的是「服务层怎么调 DAO、DAO 的行怎么变成 Identity」。
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

from backend.data.dao.rbac_dao import RbacDao
from backend.data.sql.audit import SYSTEM_USER_ID
from backend.security.rbac import DEFAULT_ROLES, RbacService


async def test_ensure_default_roles_seeds_every_role_and_scope() -> None:
    """内置角色与权限点全量交给 DAO，审计身份固定为系统用户。"""
    with patch.object(
        RbacDao, "ensure_roles_and_permissions", new=AsyncMock(return_value=(0, 0))
    ) as seeded:
        await RbacService.ensure_default_roles()

    roles, permissions = seeded.await_args.args
    assert {r[0] for r in roles} == set(DEFAULT_ROLES)
    assert len(permissions) == sum(len(scopes) for _, scopes in DEFAULT_ROLES.values())
    assert seeded.await_args.kwargs["user_id"] == SYSTEM_USER_ID


async def test_resolve_identity_maps_row_to_identity() -> None:
    """库行转 Identity：is_primary 归一成 bool，scopes 原样透传。"""
    row = {"role_name": "tenant_admin", "tenant_is_primary": 1, "scopes": ["qa:ask"]}
    with patch.object(RbacDao, "get_identity", new=AsyncMock(return_value=row)):
        identity = await RbacService.resolve_identity(2001, 200)

    assert identity is not None
    assert identity.user_id == 2001
    assert identity.tenant_id == 200
    assert identity.role_name == "tenant_admin"
    assert identity.tenant_is_primary is True
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
