"""
gen_schema - 依据 backend/models 的 SQLAlchemy ORM 自动生成 PostgreSQL DDL。

设计文档要求复用 RAG-Ultra 的配置中心审批流与 API 日志持久化结构，故表结构与之对齐：
  - agent_config_change_request / agent_config_review ：配置中心审批流（无 tenant_id）
  - agent_api_call_log ：API 调用日志（一行一请求）
其余表为 agent-platform 核心/业务模型。列默认值由 ORM 在写入时提供（Python 侧 default），
故 DDL 不含服务器端 DEFAULT；自增主键用 BIGSERIAL/SERIAL，JSON 用 JSONB。

用法：python scripts/gen_schema.py [输出路径，默认 scripts/schema.sql]
依赖：仅 SQLAlchemy（无需连接数据库，使用 postgresql 方言离线编译）。
"""
from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import CreateIndex, CreateTable
from sqlalchemy.dialects.postgresql import dialect as pg_dialect

# 确保 backend 包在 sys.path（脚本以项目根运行：python scripts/gen_schema.py）
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from backend.orm_models import Base  # noqa: E402


def _ddl() -> str:
    dialect = pg_dialect()
    lines: list[str] = [
        "-- ============================================================",
        "-- agent-platform 元数据表（PostgreSQL）",
        "-- 本文件由 scripts/gen_schema.py 依据 backend/models 自动生成，请勿手改；",
        "-- 模型变更后运行 `python scripts/gen_schema.py` 重新生成本文件。",
        "-- 说明：列默认值由 ORM 在写入时提供，DDL 不含服务器端 DEFAULT；",
        "--       自增主键用 BIGSERIAL/SERIAL，JSON 列用 JSONB，时间列用 TIMESTAMP。",
        "-- ============================================================",
        "",
    ]
    for table in Base.metadata.sorted_tables:
        lines.append(str(CreateTable(table).compile(dialect=dialect)).strip() + ";")
        lines.append("")
        for idx in table.indexes:
            lines.append(str(CreateIndex(idx).compile(dialect=dialect)).strip() + ";")
            lines.append("")
    return "\n".join(lines)


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else (ROOT / "scripts" / "schema.sql")
    out.write_text(_ddl(), encoding="utf-8")
    print(f"已生成 schema: {out} ({len(Base.metadata.sorted_tables)} 张表)")


if __name__ == "__main__":
    main()
