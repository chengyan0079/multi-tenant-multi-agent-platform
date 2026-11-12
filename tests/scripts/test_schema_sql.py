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


def test_user_has_identity_flag_columns() -> None:
    """登录链路查 is_super_admin / enabled，两列必须在 DDL 里，否则新库登录 500。"""
    block = re.search(r'CREATE TABLE IF NOT EXISTS "agent_user" \((.*?)\n\);', SCHEMA_SQL, re.S)
    assert block is not None
    assert "is_super_admin BOOLEAN" in block.group(1)
    assert "enabled BOOLEAN" in block.group(1)


def test_uuid_default_uses_builtin() -> None:
    """PG13+ 内置 gen_random_uuid()：不再依赖 uuid-ossp 扩展所在 schema。"""
    assert "DEFAULT gen_random_uuid()" in SCHEMA_SQL
    assert "uuid_generate_v4()" not in SCHEMA_SQL
    assert "CREATE EXTENSION" not in SCHEMA_SQL


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


def test_two_builtin_roles_seeded() -> None:
    """预置 2 个内置角色：admin(1) 与 tenant_admin(5)；其余角色由前端创建。

    tenant_admin 必须预置：admin/tenant.py 建租户时按 name 取该角色，缺则建租户失败。
    """
    assert "(1, 'admin'" in SEED_SQL
    assert "(5, 'tenant_admin'" in SEED_SQL
    assert "(2, 'teacher'" not in SEED_SQL
    assert "(1, 'user:page')" in SEED_SQL
    assert "(1, 'rbac:menu')" in SEED_SQL


def test_audit_scope_is_read_only() -> None:
    """审计只读：种子里不写入 audit:update / audit:add。"""
    assert "'audit:update'" not in SEED_SQL
    assert "'audit:add'" not in SEED_SQL


def test_super_admin_has_no_business_scope() -> None:
    """超管只做基建：基建域 + 平台域，业务域 scope 一个都不给。"""
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from backend.security.rbac import Business, VALID_SCOPES

    business = {v for v in VALID_SCOPES if v.split(":")[0] in {e.value for e in Business}}
    assert business, "业务域 scope 不应为空"
    for scope in business:
        assert f"(1, '{scope}')" not in SEED_SQL, f"超管不应持有业务域 {scope}"


def test_tenant_admin_has_full_business_scope() -> None:
    """租户管理员持有全部业务域 scope + 租户自管平台域（含 config/audit/dashboard）。"""
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from backend.security.rbac import Business, VALID_SCOPES

    business = {v for v in VALID_SCOPES if v.split(":")[0] in {e.value for e in Business}}
    for scope in business:
        assert f"(5, '{scope}')" in SEED_SQL, f"租户管理员缺少业务域 {scope}"
    for scope in (
        "user:page", "role:page", "message:page", "rbac:menu",
        "config:page", "config:rollback", "audit:page", "dashboard:view",
    ):
        assert f"(5, '{scope}')" in SEED_SQL, f"租户管理员缺少自管平台域 {scope}"


def test_tenant_admin_has_no_platform_admin_scope() -> None:
    """平台级管理（agent/model/tool/menu/tenant）仍只归超管。"""
    for scope in ("agent:page", "model:page", "tool:page", "menu:page", "tenant:page"):
        assert f"(5, '{scope}')" not in SEED_SQL
        assert f"(1, '{scope}')" in SEED_SQL


def test_unified_menu_seeded() -> None:
    """/consultation 父子菜单与前端 RequireScope 的 scope 对齐。"""
    assert "'统一咨询', '/consultation'" in SEED_SQL
    assert "'/consultation/chat'" in SEED_SQL
    assert "'/consultation/sessions'" in SEED_SQL
    assert "'unified:menu'" in SEED_SQL
    assert "'unified_session:page'" in SEED_SQL


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
    """会话/运行/消息都要带 user_id，否则同租户内无法按用户隔离。

    agent_run 台账已按设计下线（写入链路归并到 agent_unified_turn，看板改由 API 日志兜底），
    故用统一会话历史表 agent_unified_turn 替代校验。
    """
    for table in ("agent_thread", "agent_unified_turn"):
        block = re.search(
            rf"CREATE TABLE IF NOT EXISTS {table} \((.*?)\n\);", SCHEMA_SQL, re.S
        )
        assert block is not None, f"未找到 {table} 建表语句"
        assert re.search(r"^\s+user_id BIGINT NOT NULL", block.group(1), re.M), (
            f"{table} 缺少 user_id"
        )
    assert "ix_agent_thread_tenant_user" in SCHEMA_SQL
    assert "ix_agent_unified_turn_user_id" in SCHEMA_SQL


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
