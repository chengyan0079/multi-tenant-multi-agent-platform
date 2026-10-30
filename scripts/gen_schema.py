"""
gen_schema - 依据 backend/data/postgres 的 SQLAlchemy ORM 自动生成 PostgreSQL DDL。

设计文档要求复用配置中心审批流与 API 日志持久化结构，故表结构与之对齐：
  - agent_config_approval / agent_config_review ：配置中心审批流（无 tenant_id）
  - agent_api_call_log ：API 调用日志（一行一请求）
其余表为 agent-platform 核心/业务模型。审计列（create_user_id 等）不带 DEFAULT，
由代码写入：请求期由 before_flush 从上下文注入，非请求期显式传值。自增主键用 BIGSERIAL/SERIAL，JSON 用 JSONB。

用法：python scripts/gen_schema.py [输出路径，默认 scripts/schema.sql]
依赖：仅 SQLAlchemy（无需连接数据库，使用 postgresql 方言离线编译）。
"""
from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy.schema import CreateIndex, CreateTable
from sqlalchemy.dialects.postgresql import dialect as pg_dialect

# 确保 backend 包在 sys.path（脚本以项目根运行：python scripts/gen_schema.py）
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.data.postgres import Base  # noqa: E402
from backend.data.postgres.agent.agent import AgentCapabilityPolicy, AgentModel  # noqa: E402
from backend.data.postgres.agent.agent_model import AgentModelRel  # noqa: E402
from backend.data.postgres.agent.model_registry import ModelRegistry  # noqa: E402
from backend.data.postgres.auth.menu import Menu  # noqa: E402
from backend.data.postgres.auth.users import User, Tenant  # noqa: E402
from backend.data.postgres.ops.outbox import AgentOutbox, AgentDeadLetter  # noqa: E402

# RBAC 默认数据（角色 / 权限点）；role_id 为整数业务键，但代码一律按 role.name 判定。
# 只预置平台超管 admin 一个固定角色：超管身份以 agent_user.is_super_admin 为准，
# 不依赖 agent_role 记录；其余角色（student/teacher/tenant_admin 等）由超管在前端创建，
# 运行期权限点完全以 agent_role_permission 表为准。
# scope 格式：资源:动作，新增权限点须在 backend/security/rbac.py 的 Scope 登记，
# 散落的字符串字面量会在 require_scope 校验时立即报错。
# 幂等可重复执行（ON CONFLICT DO NOTHING）。
SEED_RBAC = (
    "-- ============================================================\n"
    "-- 默认数据：RBAC 种子（仅 admin 角色 + 超管权限点）\n"
    "-- 角色判定一律按 agent_role.name，代码不读 role_id 数字；\n"
    "-- 超管身份以 agent_user.is_super_admin 标记为准（不依赖本表记录）；\n"
    "-- 其余角色（含 tenant_admin）不在此预置，由超管在前端手动创建；\n"
    "-- scope 格式：资源:动作（资源=agent/基础设施名，动作=ask/page/update/add/delete/upload/download/review/status）\n"
    "-- 幂等可重复执行（ON CONFLICT DO NOTHING）。\n"
    "-- ============================================================\n\n"
    "INSERT INTO agent_role (role_id, name, description, create_at, create_user_id, update_user_id) VALUES\n"
    "(1, 'admin', '平台超管（全局唯一，以 agent_user.is_super_admin 为准）', now(), (SELECT id FROM \"agent_user\" WHERE username='admin'), (SELECT id FROM \"agent_user\" WHERE username='admin'))\n"
    "ON CONFLICT (role_id) DO NOTHING;\n\n"
    "INSERT INTO agent_role_permission (role_id, scope) VALUES\n"
    "-- 1=平台超管：基建域 config/agent/model + 平台域 audit/message/auth/user/rbac/menu/tenant 全权限；不含任何业务域（qa/exam/interview/resume/knowledge）\n"
    "--   权限点按 list/page/view/add/update/delete/status/review 拆分，菜单可见性与接口访问一致；\n"
    "--   配置中心复核用 config:execute（无 config:review 这一权限点，Scope 未登记）。\n"
    "(1, 'dashboard:view'),\n"
    "(1, 'config:page'),\n"
    "(1, 'config:view'),\n"
    "(1, 'config:add'),\n"
    "(1, 'config:update'),\n"
    "(1, 'config:execute'),\n"
    "(1, 'config:delete'),\n"
    "(1, 'agent:page'),\n"
    "(1, 'agent:list'),\n"
    "(1, 'agent:view'),\n"
    "(1, 'agent:add'),\n"
    "(1, 'agent:update'),\n"
    "(1, 'agent:delete'),\n"
    "(1, 'agent:status'),\n"
    "(1, 'model:page'),\n"
    "(1, 'model:view'),\n"
    "(1, 'model:add'),\n"
    "(1, 'model:update'),\n"
    "(1, 'model:delete'),\n"
    "(1, 'model:status'),\n"
    "(1, 'auth:page'),\n"
    "(1, 'auth:update'),\n"
    "(1, 'rbac:page'),\n"
    "(1, 'rbac:add'),\n"
    "(1, 'rbac:update'),\n"
    "(1, 'rbac:delete'),\n"
    "(1, 'user:page'),\n"
    "(1, 'user:view'),\n"
    "(1, 'user:add'),\n"
    "(1, 'user:update'),\n"
    "(1, 'user:delete'),\n"
    "(1, 'user:status'),\n"
    "(1, 'tenant:page'),\n"
    "(1, 'tenant:view'),\n"
    "(1, 'tenant:add'),\n"
    "(1, 'tenant:update'),\n"
    "(1, 'tenant:delete'),\n"
    "(1, 'tenant:status'),\n"
    "(1, 'audit:page'),\n"
    "(1, 'audit:view'),\n"
    "(1, 'message:page'),\n"
    "(1, 'message:view'),\n"
    "(1, 'message:status'),\n"
    "(1, 'menu:page'),\n"
    "(1, 'menu:add'),\n"
    "(1, 'menu:update'),\n"
    "(1, 'menu:delete'),\n"
    "(1, 'file:page'),\n"
    "(1, 'file:view'),\n"
    "(1, 'file:upload'),\n"
    "(1, 'file:download'),\n"
    "(1, 'menu:status')\n"
    "ON CONFLICT (role_id, scope) DO NOTHING;\n"
)

# 默认数据：只预置平台超管账号。
# 登录查 user.username；密码为明文占位，仅本地开发使用。
# 超管身份只认 agent_user.is_super_admin，不挂租户（tenant_id 为 NULL）。
SEED_DEV = (
    "-- ============================================================\n"
    "-- 默认数据：平台超管账号（登录认证主表）\n"
    "-- 超管身份只认 agent_user.is_super_admin，不挂租户（tenant_id 为 NULL）；\n"
    "-- 租户、其他账号、角色/权限分配一律由超管在前端手动创建，脚本不预置。\n"
    "-- 密码 123456，明文存储；登录只查 user.username。\n"
    "-- ============================================================\n\n"
    "INSERT INTO \"agent_user\" (username, name, password, tenant_id, is_super_admin) VALUES\n"
    "('admin', 'admin', '123456', NULL, true)\n"
    "ON CONFLICT (username) DO NOTHING;\n"
)

# 默认数据：menu（按 scope 下发）。scope=NULL 表示登录即可见，
# 其余按角色权限点过滤；/agents /tools /models 仅超管可见，/config 为协同流程所有角色可见。
SEED_MENU = (
    "-- ============================================================\n"
    "-- 默认数据：menu（菜单按 scope 下发）\n"
    "-- scope=NULL 表示登录即可见；\n"
    "-- /agents /tools /models 只授予超管角色；/config 为协同流程（所有角色可见）；\n"
    "-- /audit 授予超管与 tenant_admin。\n"
    "-- 审计日志/配置中心/权限中心下设子菜单；租户管理已移入权限中心。\n"
    "-- ============================================================\n\n"
    "CREATE UNIQUE INDEX IF NOT EXISTS uk_menu_path ON agent_menu (path);\n\n"
    "INSERT INTO agent_menu (name, path, icon, parent_id, sort_order, visible, scope) VALUES\n"
    "('监控概览', '/dashboard', 'DashboardOutlined', 0, 1, true, 'dashboard:view'),\n"
    "('会话运行', '/sessions', 'MessageOutlined', 0, 2, true, 'qa:page'),\n"
    "('智能体管理', '/agents', 'RobotOutlined', 0, 3, true, 'agent:page'),\n"
    "('工具与插件', '/tools', 'ToolOutlined', 0, 4, true, 'agent:update'),\n"
    "('模型配置', '/models', 'DeploymentUnitOutlined', 0, 5, true, 'model:page'),\n"
    "('配置中心', '/config', 'SettingOutlined', 0, 6, true, 'config:page'),\n"
    "('审计日志', '/audit', 'FileSearchOutlined', 0, 7, true, 'audit:page'),\n"
    "('权限中心', '/rbac', 'SafetyCertificateOutlined', 0, 8, true, 'rbac:page'),\n"
    "('咨询问答', '/qa', 'CommentOutlined', 0, 9, true, 'qa:page')\n"
    "ON CONFLICT (path) DO NOTHING;\n\n"
    "-- 审计日志：三个审计表的分页查询/过滤（业务审计 / 登录日志 / API 调用日志）\n"
    "INSERT INTO agent_menu (name, path, icon, parent_id, sort_order, visible, scope) VALUES\n"
    "('业务审计', '/audit/operation', 'FileTextOutlined', (SELECT id FROM agent_menu WHERE path='/audit'), 1, true, 'audit:page'),\n"
    "('登录日志', '/audit/login', 'LoginOutlined', (SELECT id FROM agent_menu WHERE path='/audit'), 2, true, 'audit:page'),\n"
    "('调用日志', '/audit/api', 'ApiOutlined', (SELECT id FROM agent_menu WHERE path='/audit'), 3, true, 'audit:page')\n"
    "ON CONFLICT (path) DO NOTHING;\n\n"
    "-- 配置中心：配置申请 / 配置审核\n"
    "INSERT INTO agent_menu (name, path, icon, parent_id, sort_order, visible, scope) VALUES\n"
    "('配置列表', '/config/request', 'FormOutlined', (SELECT id FROM agent_menu WHERE path='/config'), 1, true, 'config:page'),\n"
    "('配置审核', '/config/review', 'AuditOutlined', (SELECT id FROM agent_menu WHERE path='/config'), 2, true, 'config:page')\n"
    "ON CONFLICT (path) DO NOTHING;\n\n"
    "-- 权限中心：租户管理（从顶级移入） + 用户管理 + 角色管理 + 菜单管理\n"
    "INSERT INTO agent_menu (name, path, icon, parent_id, sort_order, visible, scope) VALUES\n"
    "('租户管理', '/tenants', 'TeamOutlined', (SELECT id FROM agent_menu WHERE path='/rbac'), 1, true, 'tenant:page'),\n"
    "('用户管理', '/users', 'UserOutlined', (SELECT id FROM agent_menu WHERE path='/rbac'), 2, true, 'rbac:page'),\n"
    "('角色管理', '/roles', 'KeyOutlined', (SELECT id FROM agent_menu WHERE path='/rbac'), 3, true, 'rbac:page'),\n"
    "('菜单管理', '/menus', 'MenuOutlined', (SELECT id FROM agent_menu WHERE path='/rbac'), 4, true, 'rbac:page')\n"
    "ON CONFLICT (path) DO NOTHING;\n\n"
    "-- 文件管理：文件列表（分页 / 详情 / 上传 / 下载），按租户隔离，超管查全部\n"
    "INSERT INTO agent_menu (name, path, icon, parent_id, sort_order, visible, scope) VALUES\n"
    "('文件管理', '/files', 'FolderOpenOutlined', 0, 10, true, 'file:page')\n"
    "ON CONFLICT (path) DO NOTHING;\n\n"
    "INSERT INTO agent_menu (name, path, icon, parent_id, sort_order, visible, scope) VALUES\n"
    "('文件列表', '/files/list', 'FileOutlined', (SELECT id FROM agent_menu WHERE path='/files'), 1, true, 'file:page')\n"
    "ON CONFLICT (path) DO NOTHING;\n"
)


# 默认数据：模型注册表（4 类默认模型，开箱即用；api_key 留空由超管在界面填）
# 其余字段取当前 .env 默认（LLM_API_BASE / LLM_MODEL 等）。
SEED_MODEL = (
    "-- ============================================================\n"
    "-- 默认数据：agent_model_registry（模型配置注册表）\n"
    "-- 4 类默认模型各一条；api_key 留空，由超管在 /models 界面填；\n"
    "-- 其余字段取当前 .env 默认（LLM_API_BASE / LLM_MODEL 等）。\n"
    "-- ============================================================\n\n"
    "INSERT INTO agent_model_registry (\n"
    "    model_type, name, provider, base_url, api_key, endpoint_path,\n"
    "    temperature, timeout_s, max_retries, enabled, sort_order, description,\n"
    "    create_user_id, update_user_id) VALUES\n"
    "('llm', 'deepseek-chat', 'openai', 'http://localhost:8000/v1', NULL, NULL,\n"
    "    0.2, 60, 2, true, 1, '默认 LLM（DeepSeek，经 OpenAI 兼容网关）', (SELECT id FROM \"agent_user\" WHERE username='admin'), (SELECT id FROM \"agent_user\" WHERE username='admin')),\n"
    "('embedding', 'bge-m3', 'local', NULL, NULL, 'models/BAAI/bge-m3',\n"
    "    NULL, NULL, NULL, true, 1, 'BGE-M3 向量化（本地 FlagEmbedding）', (SELECT id FROM \"agent_user\" WHERE username='admin'), (SELECT id FROM \"agent_user\" WHERE username='admin')),\n"
    "('reranker', 'bge-reranker-v2-m3', 'local', NULL, NULL, 'models/BAAI/bge-reranker-v2-m3',\n"
    "    NULL, NULL, NULL, true, 1, 'BGE-Reranker-v2-m3 精排（本地）', (SELECT id FROM \"agent_user\" WHERE username='admin'), (SELECT id FROM \"agent_user\" WHERE username='admin')),\n"
    "('classifier', 'bert-intent-zh', 'local', NULL, NULL, 'models/bert-intent-recognition-model',\n"
    "    NULL, NULL, NULL, true, 1, '中文意图分类（离线训练产物）', (SELECT id FROM \"agent_user\" WHERE username='admin'), (SELECT id FROM \"agent_user\" WHERE username='admin'))\n"
    "ON CONFLICT (model_type, name) DO NOTHING;\n"
)


# 默认数据：Agent 目录（4 个内置 Agent，agent_type 与代码 AgentRegistry 注册一致）
# 仅持久化可展示元数据；图的 build_graph 由代码注册，本表不存图结构。
SEED_AGENT = (
    "-- ============================================================\n"
    "-- 默认数据：agent（Agent 目录，agent_type 与代码注册一致）\n"
    "-- 仅持久化可展示元数据；build_graph 由代码注册，本表不存图结构。\n"
    "-- ============================================================\n\n"
    "INSERT INTO agent (\n"
    "    agent_type, name, description, input_schema,\n"
    "    enabled, version, create_user_id, update_user_id) VALUES\n"
    "('qa', '问答助手', '智能问答与多轮对话', NULL,\n"
    "    true, '1.0.0', (SELECT id FROM \"agent_user\" WHERE username='admin'), (SELECT id FROM \"agent_user\" WHERE username='admin')),\n"
    "('exam', '考试助手', '组卷、答题与评测', NULL,\n"
    "    true, '1.0.0', (SELECT id FROM \"agent_user\" WHERE username='admin'), (SELECT id FROM \"agent_user\" WHERE username='admin')),\n"
    "('resume', '简历助手', '简历解析与优化建议', NULL,\n"
    "    true, '1.0.0', (SELECT id FROM \"agent_user\" WHERE username='admin'), (SELECT id FROM \"agent_user\" WHERE username='admin')),\n"
    "('interview', '面试助手', '模拟面试与反馈', NULL,\n"
    "    true, '1.0.0', (SELECT id FROM \"agent_user\" WHERE username='admin'), (SELECT id FROM \"agent_user\" WHERE username='admin'))\n"
    "ON CONFLICT (agent_type) DO NOTHING;\n"
)


def _ddl() -> str:
    dialect = pg_dialect()
    lines: list[str] = [
        "-- ============================================================",
        "-- agent-platform 数据库初始化脚本（PostgreSQL，可直接执行）",
        "-- 本文件由 scripts/gen_schema.py 依据 backend/data/postgres 自动生成，请勿手改；",
        "-- 模型变更后运行 `python scripts/gen_schema.py` 重新生成本文件。",
        "--",
        "-- 特性：① 数据库不存在则创建  ② 自动切换数据库  ③ 每表用 IF NOT EXISTS 存在判断（不删已有表）",
        "--       ④ 表落入专属 agent_platform schema（CREATE SCHEMA + SET search_path，不污染 public）",
        "--       ⑤ 末尾加载 RBAC 默认数据（幂等，可重复执行）。",
        "-- 用法： psql -U <管理员> -h <host> -f scripts/schema.sql",
        "--       首次执行需具备建库权限；重复执行安全（CREATE IF NOT EXISTS / INSERT ON CONFLICT）。",
        "-- ============================================================",
        "",
        "\\set ON_ERROR_STOP on",
        "",
        "-- ① 数据库不存在则创建（PostgreSQL 无 CREATE DATABASE IF NOT EXISTS，使用 \\gexec 技巧）",
        "SELECT 'CREATE DATABASE agent_platform WITH TEMPLATE template0 ENCODING ''UTF8'' LC_COLLATE ''C'' LC_CTYPE ''C'''",
        "WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'agent_platform')\\gexec",
        "",
        "-- ② 切换到目标库（后续所有语句均在 agent_platform 中执行）",
        "\\c agent_platform",
        "",
        "-- ③ 创建专属 schema",
        "CREATE SCHEMA IF NOT EXISTS agent_platform;",
        "",
        "-- ④ 启用 UUID 生成函数（装入 agent_platform schema）",
        "--    search_path 仅含 agent_platform，若扩展留在 public 会找不到 uuid_generate_v4()",
        'CREATE EXTENSION IF NOT EXISTS "uuid-ossp" SCHEMA agent_platform;',
        "",
        "-- ⑤ 切换 search_path，后续对象全部落在 agent_platform",
        "--    与应用连接 server_settings.search_path 保持一致，不占用 public",
        "SET search_path TO agent_platform;",
        "",
    ]
    for table in Base.metadata.sorted_tables:
        lines.append(str(CreateTable(table, if_not_exists=True).compile(dialect=dialect)).strip() + ";")
        lines.append("")
        # table.indexes 是集合，直接迭代每次顺序不同；按名字排序保证生成结果稳定
        for idx in sorted(table.indexes, key=lambda i: i.name or ""):
            lines.append(str(CreateIndex(idx, if_not_exists=True).compile(dialect=dialect)).strip() + ";")
            lines.append("")
        # PostgreSQL 表/列备注（COMMENT ON）
        if getattr(table, "comment", None):
            lines.append(
                f"COMMENT ON TABLE \"{table.name}\" IS '{table.comment.replace(chr(39), chr(39) * 2)}';"
            )
        for col in table.columns:
            if getattr(col, "comment", None):
                lines.append(
                    f"COMMENT ON COLUMN \"{table.name}\".{col.name} IS "
                    f"'{col.comment.replace(chr(39), chr(39) * 2)}';"
                )
        lines.append("")
    # updated_at 触发器：任意行更新时自动刷新 updated_at 为当前时间（PostgreSQL 规范）
    # 统一使用 update_updated_at_column()，并通过 DO 块遍历「所有含 updated_at 列的表」，
    # 表名由 metadata 动态生成，避免硬编码遗漏。
    updated_tables = [t.name for t in Base.metadata.sorted_tables if "updated_at" in t.c]
    lines.append("-- ============================================================")
    lines.append("-- 自动更新 updated_at 触发器")
    lines.append("-- 覆盖所有含 updated_at 列的表（表名由模型动态生成）")
    lines.append("-- ============================================================")
    lines.append("CREATE OR REPLACE FUNCTION update_updated_at_column()")
    lines.append("RETURNS TRIGGER AS $$")
    lines.append("BEGIN")
    lines.append("    NEW.updated_at = NOW();")
    lines.append("    RETURN NEW;")
    lines.append("END;")
    lines.append("$$ LANGUAGE plpgsql;")
    lines.append("")
    if updated_tables:
        lines.append("DO $$")
        lines.append("DECLARE")
        lines.append("    t TEXT;")
        lines.append("BEGIN")
        lines.append("    FOREACH t IN ARRAY ARRAY[")
        for i, tname in enumerate(updated_tables):
            suffix = "," if i < len(updated_tables) - 1 else ""
            lines.append(f"        '{tname}'{suffix}")
        lines.append("    ]")
        lines.append("    LOOP")
        # 表名/触发器名用 %I（标识符格式符），自动加双引号；否则 user 等保留字会语法错
        lines.append("        EXECUTE format('")
        lines.append("            DROP TRIGGER IF EXISTS trg_%I_updated_at ON %I;")
        lines.append("            CREATE TRIGGER trg_%I_updated_at")
        lines.append("            BEFORE UPDATE ON %I")
        lines.append("            FOR EACH ROW")
        lines.append("            WHEN (OLD IS DISTINCT FROM NEW)")
        lines.append("            EXECUTE FUNCTION update_updated_at_column();")
        lines.append("        ', t, t, t, t);")
        lines.append("    END LOOP;")
        lines.append("END;")
        lines.append("$$;")
    return "\n".join(lines)


def _normalize_timestamp_precision(sql: str) -> str:
    """统一所有时间列为秒级（TIMESTAMP(0)）。

    ORM 里通用的是 DateTime（PostgreSQL 默认精度 6 位微秒），这里在产出阶段统一收敛，
    保证 schema.sql 与重生成结果一致：
      - 列类型      TIMESTAMP WITHOUT TIME ZONE  -> TIMESTAMP(0) WITHOUT TIME ZONE
      - 列默认值    DEFAULT now()                -> DEFAULT date_trunc('second', now())
      - 触发器      NEW.updated_at = NOW()       -> date_trunc('second', NOW())
      - 种子显式值  now(),                       -> date_trunc('second', now()),
    应用日志（loguru 的 {time:...SSS} 毫秒）不在此范围，仍然保留毫秒。
    """
    sql = sql.replace("TIMESTAMP WITHOUT TIME ZONE", "TIMESTAMP(0) WITHOUT TIME ZONE")
    sql = sql.replace("DEFAULT now()", "DEFAULT date_trunc('second', now())")
    sql = sql.replace("NEW.updated_at = NOW()", "NEW.updated_at = date_trunc('second', NOW())")
    sql = sql.replace("now(),", "date_trunc('second', now()),")
    return sql


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else (ROOT / "scripts" / "schema.sql")
    content = (
        _ddl() + "\n\n" + SEED_DEV + "\n\n" + SEED_RBAC + "\n\n" + SEED_MENU
        + "\n\n" + SEED_AGENT + "\n\n" + SEED_MODEL
    )
    out.write_text(_normalize_timestamp_precision(content), encoding="utf-8")
    print(
        f"已生成 schema: {out} ({len(Base.metadata.sorted_tables)} 张表，"
        f"默认数据含角色、超管账号、菜单、agent 与模型)"
    )


if __name__ == "__main__":
    main()
