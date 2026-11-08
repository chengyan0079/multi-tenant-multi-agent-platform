"""scripts/schema.sql 结构回归测试。

只做静态检查（不连库）：字段、唯一索引、种子数据的关键取值，
以及所有 INSERT 语句的「列数 = 每行值数」，防止手工改种子时漏字段。
"""
import re
from pathlib import Path

SCHEMA_SQL = (
    Path(__file__).resolve().parents[2] / "scripts" / "schema.sql"
).read_text(encoding="utf-8")
SEED_SQL = (
    Path(__file__).resolve().parents[2] / "scripts" / "seed_data.sql"
).read_text(encoding="utf-8")


def test_tenant_has_flag_columns() -> None:
    """租户表只有启停列：租户地位平等，不再有主租户标记与唯一索引。"""
    assert "enabled BOOLEAN DEFAULT true NOT NULL" in SCHEMA_SQL
    assert "is_primary" not in SCHEMA_SQL
    assert "uk_tenant_primary" not in SCHEMA_SQL


def test_audit_tenant_id_nullable_for_super_admin() -> None:
    """超管不挂租户，审计的 tenant_id 必须允许为空，否则超管写操作会 500。"""
    block = re.search(
        r"CREATE TABLE IF NOT EXISTS agent_audit_log \((.*?)\n\);", SCHEMA_SQL, re.S
    )
    assert block is not None
    assert re.search(r"^\s+tenant_id BIGINT,\s*$", block.group(1), re.M)


def test_user_has_unique_username() -> None:
    """登录只查 username，故该列必须存在且唯一。"""
    assert "username VARCHAR(64) NOT NULL" in SCHEMA_SQL
    assert "uk_user_username" in SCHEMA_SQL


def test_menu_has_scope_column() -> None:
    """菜单按权限点下发。"""
    assert "scope VARCHAR(64)" in SCHEMA_SQL


def test_identity_uniqueness_indexes() -> None:
    """每租户管理员唯一的库层兜底（role_id=5，按角色名判定）。

    超管不写 agent_user_tenant（身份以 agent_user.is_super_admin 为准），故不再有
    uk_aut_super_admin；该索引断言已移除。
    """
    assert "uk_aut_tenant_admin" in SCHEMA_SQL


def test_admin_role_seeded_only() -> None:
    """角色目录只预置超管 admin；其余角色（tenant_admin 等）由前端创建，不在此落库。"""
    assert "(1, 'admin'" in SEED_SQL
    assert "(5, 'tenant_admin'" not in SEED_SQL
    assert "(2, 'teacher'" not in SEED_SQL
    assert "(1, 'user:page')" in SEED_SQL
    assert "(1, 'rbac:menu')" in SEED_SQL


def test_audit_scope_is_read_only() -> None:
    """种子里不写入 audit:update，审计只读。"""
    assert "'audit:update'" not in SEED_SQL


def test_config_center_only_for_super_admin() -> None:
    """配置中心只归超管：teacher / tenant_admin 不得有 config:read。"""
    assert "(2, 'config:read')" not in SEED_SQL
    assert "(5, 'config:read')" not in SEED_SQL


def test_audit_only_for_admin() -> None:
    """审计只读权限只给超管 admin；tenant_admin 不在此预置（由前端创建后再配）。"""
    assert "(1, 'audit:page')" in SEED_SQL
    assert "(2, 'audit:read')" not in SEED_SQL
    assert "(5, 'audit:page')" not in SEED_SQL


def test_analyst_role_removed() -> None:
    """analyst 角色已删除：角色目录、权限点、用户与分配都不应残留。"""
    assert "'analyst'" not in SEED_SQL
    assert "analyst-c" not in SEED_SQL
    for scope in ("qa:read", "interview:read", "resume:read", "exam:read", "knowledge:read"):
        assert f"(4, '{scope}')" not in SEED_SQL
    assert "(3002, 300, 4" not in SEED_SQL


def test_menu_scope_for_rbac_is_read() -> None:
    """权限中心菜单按读权限下发，避免只有写权限的角色看不见页面。"""
    assert "true, 'rbac:menu')" in SEED_SQL


def test_gen_schema_is_ddl_only() -> None:
    """DDL 生成器只产出建表语句，种子已拆到 seed_data.sql。"""
    source = (
        Path(__file__).resolve().parents[2] / "scripts" / "gen_schema.py"
    ).read_text(encoding="utf-8")
    assert "INSERT INTO" not in source
    for name in ("SEED_RBAC", "SEED_DEV", "SEED_MENU", "SEED_MODEL", "SEED_AGENT"):
        assert name not in source


def test_no_by_suffix_columns() -> None:
    """操作者列统一 `*_user_id`：DDL 里不应再出现 `*_by` 列。"""
    assert not re.search(r"^\s+\w+_by\s", SCHEMA_SQL, re.M)


def test_redundant_tables_removed() -> None:
    """会话摘要/人工转接/消息轨迹已下线，schema 不应再生成这三张表。"""
    for table in ("agent_qa_sessions", "agent_escalation", "agent_message"):
        assert f"CREATE TABLE IF NOT EXISTS {table}" not in SCHEMA_SQL


def test_agent_tables_are_user_scoped() -> None:
    """会话/运行/消息都要带 user_id，否则同租户内无法按用户隔离。"""
    for table in ("agent_thread", "agent_run"):
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
    cleaned = SEED_SQL.replace("now()", "NOW")
    pattern = re.compile(r'INSERT INTO ([\w"]+) \(([^)]*)\) VALUES(.*?);', re.S)
    checked = 0
    for match in pattern.finditer(cleaned):
        # 含子查询（如 agent_user_tenant 用 SELECT 关联避免硬编码 id）的行无法做列数核对，跳过
        if "SELECT" in match.group(0):
            continue
        table, columns, values = match.group(1), match.group(2), match.group(3)
        column_count = len([c for c in columns.split(",") if c.strip()])
        values = values.split("ON CONFLICT")[0]
        for row in re.findall(r"\(([^()]*)\)", values):
            assert len(row.split(",")) == column_count, (
                f"{table} 行列数 {column_count} 与值数不一致：{row}"
            )
            checked += 1
    assert checked > 0, "没有解析到任何 INSERT 数据行"
