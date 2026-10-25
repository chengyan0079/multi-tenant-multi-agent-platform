"""审计日志 DAO：写入与查询（agent_audit_log，只读查询，见设计文档 §6.5）。

- 审计日志无写接口：仅由业务操作在事务内落库；
- 查询时 tenant_admin 强制按本租户过滤（由调用方传 tenant_id 实现，本 DAO 不擅自决定）；
- create_at / updated_at 由 TimestampMixin 自动维护，写入不显式给值。
"""
from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import text

from backend.data.sql import execute_write, fetch_all, session_scope

_INSERT = text(
    "INSERT INTO agent_audit_log (tenant_id, user_id, action, target, detail, result, trace_id, ip) "
    "VALUES (:tenant_id, :user_id, :action, :target, :detail, :result, :trace_id, :ip)"
)
_LIST = text(
    "SELECT id, tenant_id, user_id, action, target, detail, result, trace_id, ip, create_at "
    "FROM agent_audit_log "
    "WHERE (CAST(:tenant_id AS BIGINT) IS NULL OR tenant_id = CAST(:tenant_id AS BIGINT)) "
    "ORDER BY create_at DESC LIMIT :limit"
)


class AuditDao:
    """审计日志读写（仅 insert + select）。"""

    @staticmethod
    async def write(
        *,
        tenant_id: int,
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
        tenant_id: Optional[int] = None, limit: int = 200
    ) -> list[dict[str, Any]]:
        """按租户过滤查询（tenant_id=None 查全量，仅超管），按时间倒序。"""
        async with session_scope() as session:
            return await fetch_all(
                session, _LIST, {"tenant_id": tenant_id, "limit": limit}
            )
