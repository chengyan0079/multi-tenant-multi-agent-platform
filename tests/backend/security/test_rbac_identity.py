"""身份判定单元测试。

覆盖点：角色判定只按角色名，不看 role_id 数字；超管标记只由 is_super_admin 注入，
与租户无关（没有主租户概念）。

角色目录种子（原 DEFAULT_ROLES）已从代码移除，改由 scripts/schema.sql 静态注入，
相关校验统一放在 tests/scripts/test_schema_sql.py，这里只测代码内的判定逻辑。
"""
from backend.security.rbac import (
    Identity,
    RoleName,
    Scope,
    VALID_SCOPES,
    is_tenant_admin_role,
)


def test_tenant_admin_only_by_role_name() -> None:
    """租户管理员只认 tenant_admin，管理员角色不会被当成租户管理员。"""
    assert is_tenant_admin_role(RoleName.TENANT_ADMIN.value) is True
    assert is_tenant_admin_role(RoleName.ADMIN.value) is False
    assert is_tenant_admin_role(None) is False


def test_identity_flags() -> None:
    """is_super_admin 只由 resolve_super_admin 注入，不靠角色名/租户推导。"""
    super_admin = Identity(1, None, RoleName.ADMIN.value, [Scope.AGENT_PAGE], is_super_admin=True)
    assert super_admin.is_super_admin is True
    assert super_admin.is_tenant_admin is False
    assert super_admin.tenant_id is None

    # 租户内的 admin 角色不算超管
    tenant_scoped_admin = Identity(2, 200, RoleName.ADMIN.value, [Scope.AGENT_PAGE])
    assert tenant_scoped_admin.is_super_admin is False

    tenant_admin = Identity(3, 200, RoleName.TENANT_ADMIN.value, [Scope.QA_PAGE])
    assert tenant_admin.is_tenant_admin is True
    assert tenant_admin.is_super_admin is False

    student = Identity(4, 200, "student", [Scope.QA_ASK])
    assert student.is_super_admin is False
    assert student.is_tenant_admin is False


def test_identity_has_no_primary_tenant_field() -> None:
    """租户不再有主租户标记：Identity 上不应残留 tenant_is_primary。"""
    assert not hasattr(Identity(1, 200, "student", []), "tenant_is_primary")


def test_analyst_role_removed() -> None:
    """analyst 没有专属职责，已从角色名枚举中删除；编号 4 不回收复用。"""
    assert not hasattr(RoleName, "ANALYST")


def test_audit_scope_is_read_only() -> None:
    """审计域没有写权限点：合法权限点集合里不存在 audit:update。"""
    assert "audit:update" not in VALID_SCOPES


def test_scope_enum_covers_menu_scopes() -> None:
    """菜单表用到的 scope 都必须在合法权限点集合里，否则 require_scope 会漏配。"""
    expected = {
        "agent:page",
        "agent:update",
        "model:page",
        "tenant:page",
        "role:page",
        "user:page",
        "menu:page",
        "qa:page",
    }
    assert expected <= VALID_SCOPES
