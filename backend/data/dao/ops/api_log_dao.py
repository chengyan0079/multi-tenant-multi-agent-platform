"""API 调用日志 DAO：把一次调用的元数据落一行（agent_api_call_log）。

只写元数据（调用方/身份/方法/路径/状态/耗时），请求体与响应体不落库：
这两个字段是表膨胀的主因，且排障价值低于其代价。

落库是旁路：写失败仅告警，绝不影响接口返回。
"""
from __future__ import annotations

import json
from typing import Any, Optional

from sqlalchemy import text

from backend.app_state import app_state
from backend.common.logger import logger
from backend.data.sql import fetch_all, fetch_value, session_scope

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
_LIST = text("""
SELECT id, trace_id, caller, user_id, tenant_id, method, path, route,
       query_string, status_code, cost_ms, req_time, create_at
FROM agent_api_call_log
WHERE (CAST(:tenant_id AS BIGINT) IS NULL OR tenant_id = CAST(:tenant_id AS BIGINT))
ORDER BY req_time DESC
LIMIT :limit OFFSET :offset
""")

_COUNT = text("""
SELECT count(*) FROM agent_api_call_log
WHERE (CAST(:tenant_id AS BIGINT) IS NULL OR tenant_id = CAST(:tenant_id AS BIGINT))
""")


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
        tenant_id: Optional[int] = None, page: int = 1, page_size: int = 20
    ) -> tuple[list[dict[str, Any]], int]:
        """按租户过滤分页查询（tenant_id=None 查全量，仅超管），时间倒序。"""
        async with session_scope() as session:
            rows = await fetch_all(
                session, _LIST,
                {"tenant_id": tenant_id, "limit": page_size, "offset": (page - 1) * page_size},
            )
            total = await fetch_value(session, _COUNT, {"tenant_id": tenant_id})
            return rows, int(total)
