"""sql_dialect_validate 工具：按 db_type 校验 SQL 脚本方言关键字 + 规范化文件名(.sql)。"""

from __future__ import annotations

from typing import Any

from backend.tools.protocol import BaseTool
from backend.services.sql_script_service import ensure_sql_filename, validate_script


class SqlDialectValidateTool(BaseTool):
    """SQL 方言校验（解耦自 sql_script_service，供 Agent 通过工具调用）。"""

    name = "sql_dialect_validate"
    description = "按目标库类型校验 SQL 脚本方言关键字，并规范化脚本文件名(.sql)"

    async def run(self, **kwargs: Any) -> dict:
        text = kwargs.get("script") or kwargs.get("sql_text") or ""
        db_type = kwargs.get("db_type") or ""
        max_bytes = int(kwargs.get("max_bytes") or 16 * 1024)
        result = validate_script(text, db_type, max_bytes=max_bytes)
        result["normalized_filename"] = ensure_sql_filename(
            kwargs.get("filename") or "script"
        )
        return result
