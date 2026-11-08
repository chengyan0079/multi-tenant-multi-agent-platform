"""API 调用日志 DAO：把一次调用的元数据落一行（agent_api_call_log）。

落库是旁路：写失败仅告警，绝不影响接口返回。
"""
from __future__ import annotations

import json
from typing import Any, Optional

from sqlalchemy import text

from backend.app_state import app_state
from backend.common.logger import logger
from backend.data.sql import fetch_page, session_scope

_INSERT = text("""
INSERT INTO agent_api_call_log (
    trace_id, caller, user_id, tenant_id, method, path, route, query_string,
    req_headers, req_time, status_code, resp_time, cost_ms
) VALUES (
    :trace_id, :caller, :user_id, :tenant_id, :method, :path, :route, :query_string,
    CAST(:req_headers AS jsonb), :req_time, :status_code, :resp_time, :cost_ms
)
""")

# 需要从中间件的 record 里取的列：显式白名单，避免调用方多传字段导致绑定失败
_RECORD_KEYS = (
    "trace_id",
    "caller",
    "user_id",
    "tenant_id",
    "method",
    "path",
    "route",
    "query_string",
    "req_time",
    "status_code",
    "resp_time",
    "cost_ms",
)

# 时间倒序；tenant_id 为空表示全平台（仅超管）
_LIST_BASE = """
SELECT l.id, l.trace_id, l.caller, l.user_id,
       COALESCE(u.name, u.username,
                CASE WHEN l.user_id IS NULL THEN NULL
                     ELSE '用户#' || l.user_id::text END) AS user_name,
       l.tenant_id,
       COALESCE(t.name, CASE WHEN l.tenant_id IS NULL THEN NULL
                            ELSE '租户#' || l.tenant_id::text END) AS tenant_name,
       l.method, l.path, l.route, l.query_string, l.status_code, l.cost_ms,
       l.req_time, l.create_at
FROM agent_api_call_log l
LEFT JOIN agent_tenant t ON t.id = l.tenant_id
LEFT JOIN "agent_user" u ON u.id = l.user_id
"""

_COUNT_BASE = "SELECT count(*) FROM agent_api_call_log l"


class ApiLogDao:
    """API 调用日志落库（一条请求一行）。"""

    async def save(self, record: dict[str, Any]) -> None:
        """写入一行；引擎未就绪或写库异常时仅告警。"""
        if app_state.db_engine is None:
            return  # 数据库未启动（如单测/降级），跳过落库
        try:
            async with session_scope() as session:
                params: dict[str, Any] = {k: record.get(k) for k in _RECORD_KEYS}
                # 请求头在中间件里是 dict，text() 不负责序列化，这里显式转 JSON 文本
                headers = record.get("req_headers")
                params["req_headers"] = (
                    json.dumps(headers, ensure_ascii=False) if headers is not None else None
                )

                await session.execute(_INSERT, params)
                await session.commit()
        except Exception:  # noqa: BLE001  日志旁路：失败不影响主链路
            logger.exception("API 调用日志落库失败（不影响接口返回）")

    @staticmethod
    async def query(
        tenant_id: Optional[int] = None,
        page: int = 1,
        page_size: int = 20,
        path_prefix: str | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        conds: list[str] = []
        params: dict[str, Any] = {}
        if tenant_id is not None:
            conds.append("l.tenant_id = :tenant_id")
            params["tenant_id"] = tenant_id
        if path_prefix:
            conds.append("l.path LIKE :path_prefix")
            params["path_prefix"] = f"{path_prefix.rstrip('%')}%"
        where = f"WHERE {' AND '.join(conds)}" if conds else ""
        list_sql = text(
            f"{_LIST_BASE} {where} ORDER BY l.req_time DESC LIMIT :limit OFFSET :offset"
        )
        count_sql = text(f"{_COUNT_BASE} {where}")
        async with session_scope() as session:
            return await fetch_page(
                session, list_sql, count_sql, params,
                page=page, page_size=page_size,
            )
