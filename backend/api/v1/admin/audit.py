"""超管审计日志端点（/api/v1/admin/audit）。

超管可查全量，也可传 tenant_id 过滤某个租户；审计日志只读、无写接口（§6.5）。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from backend.common.response import success
from backend.data.dao.ops.audit_dao import AuditDao
from backend.middleware.auth import CurrentUser, get_current_user
from backend.security.security import require_scope

router = APIRouter(prefix="/audit", tags=["admin"])


@router.get("/logs", summary="审计日志（可筛租户）")
async def audit_logs(
    tenant_id: int | None = Query(None, description="不传查全量（仅超管）"),
    limit: int = Query(200, le=1000),
    _: object = Depends(require_scope("audit:read")),  # noqa: B008
    __: object = Depends(get_current_user),  # noqa: B008
) -> Any:
    rows = await AuditDao.query(tenant_id=tenant_id, limit=limit)
    return success({"items": rows, "total": len(rows)})
