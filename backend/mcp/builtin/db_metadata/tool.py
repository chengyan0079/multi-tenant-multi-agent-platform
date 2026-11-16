"""db_metadata 工具：按 connection_id 连接目标库读取元数据（DDL/索引/统计），只读。

工具与连接解耦：同一工具在运行时按 connection_id 选择数据源；
图内多次调用须传同一 connection_id（保证同一连接）。
"""

from __future__ import annotations

from typing import Any

from backend.mcp.protocol import BaseTool
from backend.services.db_connection_service import fetch_metadata


class DbMetadataTool(BaseTool):
    """目标库元数据读取（只读；运行时按 connection_id 动态选库）。"""

    name = "db_metadata"
    description = "按 connection_id 读取目标库元数据（列 DDL/索引/统计），只读"

    async def run(self, **kwargs: Any) -> dict:
        tenant_id = int(kwargs.get("tenant_id") or 0)
        connection_id = str(kwargs.get("connection_id") or "")
        tables = list(kwargs.get("target_tables") or kwargs.get("tables") or [])
        if not connection_id:
            return {"ok": False, "error": "缺少 connection_id"}
        return await fetch_metadata(tenant_id, connection_id, tables)
