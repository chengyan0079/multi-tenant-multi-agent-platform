"""
gen_schema - 依据 backend/data/postgres 的 SQLAlchemy ORM 自动生成 PostgreSQL DDL（仅建库/建表，不含种子数据）。

初始化流程：
  1) python scripts/gen_schema.py        # 生成 scripts/schema.sql（DDL）
  2) psql ... -f scripts/schema.sql      # 建库 / schema / 表 / 索引 / 注释 / 触发器
  3) psql ... -f scripts/seed_data.sql   # 可选：平台基础种子（超管 / 菜单 / agent / 模型）

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
from backend.data.postgres.agent.agent import AgentModel  # noqa: E402
from backend.data.postgres.agent.agent_model import AgentModelRel  # noqa: E402
from backend.data.postgres.agent.model_registry import ModelRegistry  # noqa: E402
from backend.data.postgres.auth.menu import Menu  # noqa: E402
from backend.data.postgres.auth.users import User, Tenant  # noqa: E402
from backend.data.postgres.ops.outbox import AgentOutbox, AgentDeadLetter  # noqa: E402


def _ddl() -> str:
    dialect = pg_dialect()
    lines: list[str] = [
        "-- ============================================================",
        "-- agent-platform 数据库初始化脚本（PostgreSQL，可直接执行）",
        "-- 本文件由 scripts/gen_schema.py 依据 backend/data/postgres 自动生成，请勿手改；",
        "-- 模型变更后运行 `python scripts/gen_schema.py` 重新生成本文件。",
        "--",
        "-- 特性：① 数据库不存在则创建  ② 自动切换数据库  ③ 每表用 IF NOT EXISTS 存在判断（不删已有表）",
        "--       ④ 表落入专属 unified_schemas schema（CREATE SCHEMA + SET search_path，不污染 public）",
        "-- 种子数据不在此文件：初始化后另行执行 scripts/seed_data.sql（平台基础 + 超管）。",
        "-- 用法： psql -U <管理员> -h <host> -f scripts/schema.sql",
        "--       首次执行需具备建库权限；重复执行安全（CREATE IF NOT EXISTS）。",
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
        "CREATE SCHEMA IF NOT EXISTS unified_schemas;",
        "",
        "-- ④ UUID 主键用 PG13+ 内置 gen_random_uuid()，不依赖 uuid-ossp 扩展",
        "",
        "-- ⑤ 切换 search_path，后续对象全部落在 unified_schemas",
        "--    与应用连接 server_settings.search_path 保持一致，不占用 public",
        "SET search_path TO unified_schemas;",
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
    # 菜单路径唯一索引：seed_data.sql 的 ON CONFLICT (path) 依赖它
    lines.append("-- ============================================================")
    lines.append("-- 菜单路径唯一索引（种子 ON CONFLICT (path) 依赖）")
    lines.append("-- ============================================================")
    lines.append("CREATE UNIQUE INDEX IF NOT EXISTS uk_menu_path ON agent_menu (path);")
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
    应用日志（loguru 的 {time:...SSS} 毫秒）不在此范围，仍然保留毫秒。
    """
    sql = sql.replace("TIMESTAMP WITHOUT TIME ZONE", "TIMESTAMP(0) WITHOUT TIME ZONE")
    sql = sql.replace("DEFAULT now()", "DEFAULT date_trunc('second', now())")
    sql = sql.replace("NEW.updated_at = NOW()", "NEW.updated_at = date_trunc('second', NOW())")
    return sql


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else (ROOT / "scripts" / "schema.sql")
    out.write_text(_normalize_timestamp_precision(_ddl()), encoding="utf-8")
    print(
        f"已生成 DDL: {out} ({len(Base.metadata.sorted_tables)} 张表，不含种子数据；"
        f"种子见 scripts/seed_data.sql)"
    )


if __name__ == "__main__":
    main()
