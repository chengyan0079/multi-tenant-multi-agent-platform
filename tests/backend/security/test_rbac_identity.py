"""身份判定单元测试。

覆盖点：超管/租户管理员只按角色名 + 租户 is_primary 判定，不看 role_id 数字。
"""
from backend.security.rbac import (
    DEFAULT_ROLES,
    Identity,
    RoleName,
    Scope,
    is_super_admin_role,
    is_tenant_admin_role,
)


def test_super_admin_requires_primary_tenant() -> None:
    """主租户内的 admin 才是超管；非主租户的 admin 不能被放大。"""
    assert is_super_admin_role(RoleName.ADMIN.value, True) is True
    assert is_super_admin_role(RoleName.ADMIN.value, False) is False


def test_super_admin_rejects_other_roles() -> None:
    """其他角色名、空角色都不算超管。"""
    assert is_super_admin_role(RoleName.TENANT_ADMIN.value, True) is False
    assert is_super_admin_role(RoleName.TEACHER.value, True) is False
    assert is_super_admin_role(None, True) is False


def test_tenant_admin_only_by_role_name() -> None:
    """租户管理员只认 tenant_admin，管理员角色不会被当成租户管理员。"""
    assert is_tenant_admin_role(RoleName.TENANT_ADMIN.value) is True
    assert is_tenant_admin_role(RoleName.ADMIN.value) is False
    assert is_tenant_admin_role(None) is False


def test_identity_flags() -> None:
    """Identity 的两个布尔量由角色名与 is_primary 推导。"""
    super_admin = Identity(1, 100, RoleName.ADMIN.value, True, [Scope.ALL.value])
    assert super_admin.is_super_admin is True
    assert super_admin.is_tenant_admin is False

    fake_admin = Identity(2, 200, RoleName.ADMIN.value, False, [Scope.ALL.value])
    assert fake_admin.is_super_admin is False

    tenant_admin = Identity(3, 200, RoleName.TENANT_ADMIN.value, False, [Scope.QA_READ.value])
    assert tenant_admin.is_tenant_admin is True
    assert tenant_admin.is_super_admin is False

    student = Identity(4, 200, RoleName.STUDENT.value, False, [Scope.QA_ASK.value])
    assert student.is_super_admin is False
    assert student.is_tenant_admin is False


def test_default_roles_align_with_role_name() -> None:
    """内置角色目录的角色名与 RoleName 一一对应。"""
    names = {name for name, _ in DEFAULT_ROLES.values()}
    assert names == {role.value for role in RoleName}
    assert len(names) == len(DEFAULT_ROLES)


def test_tenant_admin_has_no_admin_scopes() -> None:
    """租户管理员拿不到 agent 域、模型配置与租户维护权限。"""
    scopes = set(DEFAULT_ROLES[5][1])
    forbidden = (
        Scope.ALL,
        Scope.AGENT_READ,
        Scope.AGENT_WRITE,
        Scope.MODEL_READ,
        Scope.TENANT_READ,
        Scope.TENANT_WRITE,
    )
    for scope in forbidden:
        assert scope not in scopes, f"tenant_admin 不应拥有 {scope.value}"


def test_config_center_is_super_admin_only() -> None:
    """配置中心是全局配置：除超管外任何角色都不该有 config:* 。"""
    for role_id in (1, 2, 5):
        scopes = set(DEFAULT_ROLES[role_id][1])
        assert Scope.CONFIG_READ not in scopes, f"role {role_id} 不应有 config:read"
        assert Scope.CONFIG_UPDATE not in scopes, f"role {role_id} 不应有 config:update"
    # 超管拥有配置中心权限，但已收敛为三域具体点（不再用全局 ALL）
    admin_scopes = set(DEFAULT_ROLES[3][1])
    assert Scope.CONFIG_READ in admin_scopes
    assert Scope.CONFIG_REVIEW in admin_scopes
    assert Scope.ALL not in admin_scopes


def test_analyst_role_removed() -> None:
    """analyst 没有专属职责，已从角色目录与枚举中删除；编号 4 不回收复用。"""
    assert not hasattr(RoleName, "ANALYST")
    assert 4 not in DEFAULT_ROLES
    assert "analyst" not in {name for name, _ in DEFAULT_ROLES.values()}


def test_audit_visible_only_to_admin_and_tenant_admin() -> None:
    """审计日志只给超管与租户管理员，其他角色一律没有。"""
    assert Scope.AUDIT_READ in set(DEFAULT_ROLES[5][1])
    for role_id in (1, 2):
        assert Scope.AUDIT_READ not in set(DEFAULT_ROLES[role_id][1]), (
            f"role {role_id} 不应有 audit:read"
        )


def test_audit_scope_is_read_only() -> None:
    """审计域没有写权限点：枚举里不存在 audit:update。"""
    assert "audit:update" not in {scope.value for scope in Scope}


def test_scope_enum_covers_menu_scopes() -> None:
    """菜单表用到的 scope 都必须在 Scope 枚举里，否则 require_scope 会漏配。"""
    expected = {
        "agent:read",
        "agent:write",
        "model:read",
        "tenant:read",
        "rbac:read",
        "rbac:write",
        "qa:read",
    }
    assert expected <= {scope.value for scope in Scope}
