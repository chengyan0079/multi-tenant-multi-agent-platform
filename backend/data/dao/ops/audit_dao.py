"""审计日志 DAO：写入与查询（agent_audit_log）。"""
from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import text

from backend.data.sql import execute_write, fetch_one, fetch_page, session_scope

_INSERT = text(
    "INSERT INTO agent_audit_log (tenant_id, user_id, action, target, detail, result, trace_id, ip) "
    "VALUES (:tenant_id, :user_id, :action, :target, :detail, :result, :trace_id, :ip)"
)
_LIST = text(
    "SELECT id, tenant_id, user_id, action, target, detail, result, trace_id, ip, create_at "
    "FROM agent_audit_log "
    "WHERE (CAST(:tenant_id AS BIGINT) IS NULL OR tenant_id = CAST(:tenant_id AS BIGINT)) "
    "ORDER BY create_at DESC LIMIT :limit OFFSET :offset"
)
_COUNT = text(
    "SELECT count(*) FROM agent_audit_log "
    "WHERE (CAST(:tenant_id AS BIGINT) IS NULL OR tenant_id = CAST(:tenant_id AS BIGINT))"
)


class AuditDao:
    """审计日志读写（仅 insert + select）。"""

    @staticmethod
    async def write(
        *,
        tenant_id: Optional[int],
        user_id: int,
        action: str,
        target: str,
        detail: str,
        result: str = "成功",
        trace_id: Optional[str] = None,
        ip: Optional[str] = None,
    ) -> None:
        """写入一条审计（tenant_id 取 home_tenant_id，即操作者归属租户）。

        result / trace_id / ip 是后补的展示字段：前端「最近活动」要显示结果，
        排障时要能从审计直接跳到链路日志。默认「成功」兼容既有调用点。

        tenant_id 允许为空：超管不挂任何租户，其操作在审计里就是 NULL 租户
        （列已放开 NOT NULL），用 user_id 定位操作人。
        """
        async with session_scope() as session:
            await execute_write(
                session,
                _INSERT,
                {
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                    "action": action,
                    "target": target,
                    "detail": detail,
                    "result": result,
                    "trace_id": trace_id,
                    "ip": ip,
                },
            )
            await session.commit()

    @staticmethod
    async def query(
        tenant_id: Optional[int] = None, page: int = 1, page_size: int = 20
    ) -> tuple[list[dict[str, Any]], int]:
        async with session_scope() as session:
            return await fetch_page(
                session, _LIST, _COUNT, {"tenant_id": tenant_id},
                page=page, page_size=page_size,
            )

    @staticmethod
    async def get(log_id: str) -> Optional[dict[str, Any]]:
        """按主键取单条审计详情。"""
        async with session_scope() as session:
            return await fetch_one(
                session,
                text(
                    "SELECT id, tenant_id, user_id, action, target, detail, result, "
                    "trace_id, ip, create_at FROM agent_audit_log WHERE id = :id"
                ),
                {"id": log_id},
            )
