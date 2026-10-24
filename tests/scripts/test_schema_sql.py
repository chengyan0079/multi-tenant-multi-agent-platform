"""scripts/schema.sql 结构回归测试。

只做静态检查（不连库）：字段、唯一索引、种子数据的关键取值，
以及所有 INSERT 语句的「列数 = 每行值数」，防止手工改种子时漏字段。
"""
import re
from pathlib import Path

SCHEMA_SQL = (
    Path(__file__).resolve().parents[2] / "scripts" / "schema.sql"
).read_text(encoding="utf-8")


def test_tenant_has_flag_columns() -> None:
    """租户表要有启停与主租户标记，以及主租户唯一索引。"""
    assert "enabled BOOLEAN DEFAULT true NOT NULL" in SCHEMA_SQL
    assert "is_primary BOOLEAN DEFAULT false NOT NULL" in SCHEMA_SQL
    assert "uk_tenant_primary" in SCHEMA_SQL


def test_user_has_unique_username() -> None:
    """登录只查 username，故该列必须存在且唯一。"""
    assert "username VARCHAR(64) NOT NULL" in SCHEMA_SQL
    assert "uk_user_username" in SCHEMA_SQL


def test_menu_has_scope_column() -> None:
    """菜单按权限点下发。"""
    assert "scope VARCHAR(64)" in SCHEMA_SQL


def test_identity_uniqueness_indexes() -> None:
    """超管全局唯一、每租户管理员唯一的库层兜底。"""
    assert "uk_aut_super_admin" in SCHEMA_SQL
    assert "uk_aut_tenant_admin" in SCHEMA_SQL


def test_tenant_admin_role_seed() -> None:
    """角色目录要有 tenant_admin，并带上最小权限点。"""
    assert "(5, 'tenant_admin'" in SCHEMA_SQL
    assert "(5, 'rbac:write')" in SCHEMA_SQL
    assert "(5, 'rbac:read')" in SCHEMA_SQL


def test_audit_scope_is_read_only() -> None:
    """种子里不写入 audit:update，审计只读。"""
    assert "'audit:update'" not in SCHEMA_SQL


def test_config_center_only_for_super_admin() -> None:
    """配置中心只归超管：teacher / tenant_admin 不得有 config:read。"""
    assert "(2, 'config:read')" not in SCHEMA_SQL
    assert "(5, 'config:read')" not in SCHEMA_SQL


def test_audit_only_for_admin_and_tenant_admin() -> None:
    """审计只给超管与 tenant_admin：teacher 的 audit:read 已收回。"""
    assert "(2, 'audit:read')" not in SCHEMA_SQL
    assert "(5, 'audit:read')" in SCHEMA_SQL


def test_analyst_role_removed() -> None:
    """analyst 角色已删除：角色目录、权限点、用户与分配都不应残留。"""
    assert "'analyst'" not in SCHEMA_SQL
    assert "analyst-c" not in SCHEMA_SQL
    for scope in ("qa:read", "interview:read", "resume:read", "exam:read", "knowledge:read"):
        assert f"(4, '{scope}')" not in SCHEMA_SQL
    assert "(3002, 300, 4" not in SCHEMA_SQL


def test_menu_scope_for_rbac_is_read() -> None:
    """权限中心菜单按读权限下发，避免只有写权限的角色看不见页面。"""
    assert "true, 'rbac:read')" in SCHEMA_SQL


def test_gen_schema_seed_not_reverted() -> None:
    """gen_schema.py 的硬编码种子必须与 schema.sql 同步，否则重新生成会回退。"""
    source = (
        Path(__file__).resolve().parents[2] / "scripts" / "gen_schema.py"
    ).read_text(encoding="utf-8")
    assert "'audit:update'" not in source
    assert "'analyst'" not in source
    assert "(2, 'config:read')" not in source
    assert "(5, 'config:read')" not in source
    assert "(5, 'tenant_admin'" in source
    assert "true, 'rbac:read')" in source


def test_default_roles_match_schema_seed() -> None:
    """代码 DEFAULT_ROLES 与 schema.sql 权限点种子必须逐条一致，防止两处漂移。"""
    from backend.security.rbac import DEFAULT_ROLES

    block = re.search(
        r"INSERT INTO agent_role_permission \(role_id, scope\) VALUES(.*?)ON CONFLICT",
        SCHEMA_SQL,
        re.S,
    )
    assert block is not None, "未找到权限点种子段"

    seed: dict[int, set[str]] = {}
    for role_id, scope in re.findall(r"\((\d+),\s*'([^']+)'\)", block.group(1)):
        seed.setdefault(int(role_id), set()).add(scope)

    code = {
        role_id: {scope.value for scope in scopes}
        for role_id, (_, scopes) in DEFAULT_ROLES.items()
    }
    assert code == seed


def test_no_by_suffix_columns() -> None:
    """操作者列统一 `*_user_id`：DDL 里不应再出现 `*_by` 列。"""
    assert not re.search(r"^\s+\w+_by\s", SCHEMA_SQL, re.M)


def test_escalation_assignee_is_user_id() -> None:
    """转接处理人是用户ID（BIGINT，未分配为 NULL），不再是字符串。"""
    assert "assigned_to " not in SCHEMA_SQL
    assert "assigned_user_id BIGINT" in SCHEMA_SQL
    assert "ix_agent_escalation_assigned_user_id" in SCHEMA_SQL


def test_agent_tables_are_user_scoped() -> None:
    """会话/运行/消息都要带 user_id，否则同租户内无法按用户隔离。"""
    for table in ("agent_thread", "agent_run", "agent_message"):
        block = re.search(
            rf"CREATE TABLE IF NOT EXISTS {table} \((.*?)\n\);", SCHEMA_SQL, re.S
        )
        assert block is not None, f"未找到 {table} 建表语句"
        assert re.search(r"^\s+user_id BIGINT NOT NULL", block.group(1), re.M), (
            f"{table} 缺少 user_id"
        )
    assert "ix_agent_thread_tenant_user" in SCHEMA_SQL


def test_business_owner_columns_use_user_id_suffix() -> None:
    """业务表的操作者列都带 _user_id 后缀。"""
    for column in (
        "created_user_id",
        "reviewed_user_id",
        "confirmed_user_id",
        "resolved_user_id",
    ):
        assert re.search(rf"^\s+{column} BIGINT", SCHEMA_SQL, re.M), f"缺少 {column}"


def test_insert_column_counts_match() -> None:
    """每条 INSERT 的列数与每行值数一致。"""
    cleaned = SCHEMA_SQL.replace("now()", "NOW")
    pattern = re.compile(r'INSERT INTO ([\w"]+) \(([^)]*)\) VALUES(.*?);', re.S)
    checked = 0
    for match in pattern.finditer(cleaned):
        table, columns, values = match.group(1), match.group(2), match.group(3)
        column_count = len([c for c in columns.split(",") if c.strip()])
        values = values.split("ON CONFLICT")[0]
        for row in re.findall(r"\(([^()]*)\)", values):
            assert len(row.split(",")) == column_count, (
                f"{table} 行列数 {column_count} 与值数不一致：{row}"
            )
            checked += 1
    assert checked > 0, "没有解析到任何 INSERT 数据行"
