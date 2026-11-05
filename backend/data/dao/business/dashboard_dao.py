"""监控看板 DAO：跨表聚合统计（只读，不做任何写操作）。

数据范围由调用方传 `tenant_id` 决定，本 DAO 不擅自判断权限：
- `tenant_id=None` → 全平台（仅超管）；
- `tenant_id=N` → 该租户（租户管理员固定为本租户）。

隔离口径：所有带业务数据的表都以 `tenant_id` 列为边界（agent_thread / agent_message /
agent_run / agent_audit_log / agent_api_call_log / agent_capability_policy），
`agent` / `model_registry` / `agent_plugin` / `tenant` 是平台级全局表，只出现于超管视图。

时间列不统一，按表取值：业务表与审计表统一是 `create_at`（见 AuditMixin/TimestampMixin），
只有 API 日志是 `req_time`。

指标口径与前端 Dashboard 页一一对应：
- 今日调用量 = agent_api_call_log 当日条数，环比昨日同期；
- 活跃会话 = 统计区间内仍有活动的 active 会话，环比上一区间；
- 智能体总数 = 超管取 agent.enabled 数，租户取 agent_capability_policy 已开通数；
- 平均成功率 = 1 - agent_run.error/total（不是 HTTP 成功率，业务成败更贴近看板语义）。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import text

from backend.data.sql import fetch_all, fetch_one, session_scope

# 统一隔离条件；alias 为内部常量，不来自用户输入。
# 显式 CAST：:tenant_id 传 None 时 asyncpg 无从推断类型（首个出现位置是 IS NULL），
# 不转型会报 could not determine data type of parameter。
_SCOPE = "(CAST(:tenant_id AS BIGINT) IS NULL OR {t}.tenant_id = CAST(:tenant_id AS BIGINT))"
_SCOPE_ALIASES = frozenset({"l", "th", "r", "al"})


def _scope(alias: str) -> str:
    if alias not in _SCOPE_ALIASES:
        raise ValueError(f"非法表别名: {alias}")
    return _SCOPE.format(t=alias)


_STATS = text(f"""
SELECT
  (SELECT COUNT(*) FROM agent_api_call_log l
     WHERE {_scope('l')} AND l.req_time >= date_trunc('day', now())) AS api_calls_today,
  (SELECT COUNT(*) FROM agent_api_call_log l
     WHERE {_scope('l')}
       AND l.req_time >= date_trunc('day', now()) - INTERVAL '1 day'
       AND l.req_time < now() - INTERVAL '1 day') AS api_calls_prev,
  (SELECT COUNT(*) FROM agent_thread th
     WHERE {_scope('th')} AND th.status = 'active' AND th.updated_at >= :since)
     AS active_threads,
  (SELECT COUNT(*) FROM agent_thread th
     WHERE {_scope('th')} AND th.status = 'active'
       AND th.updated_at >= :prev_since AND th.updated_at < :since)
     AS active_threads_prev,
  (SELECT COUNT(*) FROM agent_run r
     WHERE {_scope('r')} AND r.create_at >= :since) AS runs,
  (SELECT COUNT(*) FROM agent_run r
     WHERE {_scope('r')} AND r.create_at >= :since AND r.status = 'error') AS error_runs,
  (SELECT COUNT(*) FROM agent_run r
     WHERE {_scope('r')} AND r.create_at >= :prev_since AND r.create_at < :since) AS runs_prev,
  (SELECT COUNT(*) FROM agent_run r
     WHERE {_scope('r')} AND r.create_at >= :prev_since AND r.create_at < :since
       AND r.status = 'error') AS error_runs_prev
""")

# 智能体总数：超管看平台存量，租户看已开通数（未配置的视为未开通，口径从简）
_AGENT_TOTAL_PLATFORM = text("SELECT COUNT(*) AS total FROM agent WHERE enabled")
_AGENT_TOTAL_TENANT = text(
    "SELECT COUNT(*) AS total FROM agent_capability_policy "
    "WHERE tenant_id = CAST(:tenant_id AS BIGINT) AND enabled"
)

# 近 N 天请求量 / 错误量：错误按 HTTP >= 400 计（4xx 参数错、5xx 服务错都算失败请求）
_REQUEST_TREND = text(f"""
SELECT
  to_char(date_trunc('day', l.req_time), 'MM-DD') AS date,
  COUNT(*) AS requests,
  COUNT(*) FILTER (WHERE l.status_code >= 400) AS errors
FROM agent_api_call_log l
WHERE {_scope('l')} AND l.req_time >= :since
GROUP BY date_trunc('day', l.req_time)
ORDER BY date_trunc('day', l.req_time)
""")

# 各智能体调用占比：graph_name 可能不等于 agent_type，取不到展示名时回落图名
_AGENT_DISTRIBUTION = text(f"""
SELECT
  COALESCE(a.name, r.graph_name) AS name,
  COUNT(*) AS value
FROM agent_run r
LEFT JOIN agent a ON a.agent_type = r.graph_name
WHERE {_scope('r')} AND r.create_at >= :since
GROUP BY COALESCE(a.name, r.graph_name)
ORDER BY value DESC, name ASC
LIMIT :limit
""")

# 时段耗时：按 4 小时一桶（与前端图表的 00/04/08/12/16/20 对齐）
_LATENCY = text(f"""
SELECT
  (EXTRACT(HOUR FROM l.req_time)::int / 4) * 4 AS bucket,
  CAST(COALESCE(AVG(l.cost_ms), 0) AS BIGINT) AS avg_ms
FROM agent_api_call_log l
WHERE {_scope('l')} AND l.req_time >= :since
GROUP BY 1
ORDER BY 1
""")

# 最近活动：审计表时间倒序；result 列是后补的，历史数据为空时按「成功」兜底
_RECENT = text(f"""
SELECT
  al.id::text AS key,
  to_char(al.create_at, 'YYYY-MM-DD HH24:MI:SS') AS time,
  COALESCE(u.username, 'user-' || al.user_id) AS "user",
  al.action,
  al.target,
  COALESCE(al.result, '成功') AS result
FROM agent_audit_log al
LEFT JOIN "agent_user" u ON u.id = al.user_id
WHERE {_scope('al')}
ORDER BY al.create_at DESC
LIMIT :limit
""")

_GLOBAL = text("""
SELECT
  (SELECT COUNT(*) FROM agent_tenant) AS tenants,
  (SELECT COUNT(*) FROM agent_tenant WHERE enabled) AS tenants_enabled,
  (SELECT COUNT(*) FROM "agent_user") AS users,
  (SELECT COUNT(*) FROM agent) AS agents,
  (SELECT COUNT(*) FROM agent WHERE enabled) AS agents_enabled,
  (SELECT COUNT(*) FROM agent_model_registry) AS models,
  (SELECT COUNT(*) FROM agent_model_registry WHERE enabled) AS models_enabled,
  (SELECT COUNT(*) FROM agent_plugin) AS plugins
""")

_RANKING = text("""
SELECT
  t.id AS tenant_id,
  t.name,
  t.enabled,
  (SELECT COUNT(*) FROM agent_thread th WHERE th.tenant_id = t.id) AS threads,
  (SELECT COUNT(*) FROM agent_run r
     WHERE r.tenant_id = t.id AND r.create_at >= :since) AS runs,
  (SELECT CAST(COALESCE(SUM(r.prompt_tokens + r.completion_tokens), 0) AS BIGINT)
     FROM agent_run r WHERE r.tenant_id = t.id AND r.create_at >= :since) AS tokens
FROM agent_tenant t
ORDER BY runs DESC, t.id ASC
LIMIT :limit
""")

# 时段桶固定 6 个，缺的桶补 0，前端不必再处理空洞
_LATENCY_BUCKETS = (0, 4, 8, 12, 16, 20)


class DashboardDao:
    """监控看板聚合查询（只读）。"""

    @staticmethod
    async def stats(
        *, tenant_id: Optional[int], since: datetime, prev_since: datetime
    ) -> dict[str, Any]:
        """看板四张卡的原始计数（含环比所需的上一区间数据）。"""
        async with session_scope() as session:
            row = await fetch_one(
                session,
                _STATS,
                {"tenant_id": tenant_id, "since": since, "prev_since": prev_since},
            )
        return row or {}

    @staticmethod
    async def agent_total(*, tenant_id: Optional[int]) -> int:
        """智能体总数：超管取平台启用数，租户取本租户已开通数。"""
        sql = _AGENT_TOTAL_PLATFORM if tenant_id is None else _AGENT_TOTAL_TENANT
        async with session_scope() as session:
            row = await fetch_one(session, sql, {"tenant_id": tenant_id})
        return int((row or {}).get("total") or 0)

    @staticmethod
    async def request_trend(
        *, tenant_id: Optional[int], since: datetime
    ) -> list[dict[str, Any]]:
        """按天请求量 / 错误量（无数据的天由端点补零）。"""
        async with session_scope() as session:
            return await fetch_all(
                session, _REQUEST_TREND, {"tenant_id": tenant_id, "since": since}
            )

    @staticmethod
    async def agent_distribution(
        *, tenant_id: Optional[int], since: datetime, limit: int = 10
    ) -> list[dict[str, Any]]:
        """各智能体运行量占比（按运行条数倒序）。"""
        async with session_scope() as session:
            return await fetch_all(
                session,
                _AGENT_DISTRIBUTION,
                {"tenant_id": tenant_id, "since": since, "limit": limit},
            )

    @staticmethod
    async def latency_by_hour(
        *, tenant_id: Optional[int], since: datetime
    ) -> list[dict[str, Any]]:
        """各时段平均耗时（固定 6 桶，每 4 小时）。"""
        async with session_scope() as session:
            rows = await fetch_all(
                session, _LATENCY, {"tenant_id": tenant_id, "since": since}
            )
        found = {int(r["bucket"]): int(r["avg_ms"] or 0) for r in rows}
        return [
            {"hour": f"{b:02d}", "avg": found.get(b, 0)} for b in _LATENCY_BUCKETS
        ]

    @staticmethod
    async def recent_activities(
        *, tenant_id: Optional[int], limit: int = 5
    ) -> list[dict[str, Any]]:
        """最近审计动作（前端「最近活动」表格）。"""
        async with session_scope() as session:
            return await fetch_all(
                session, _RECENT, {"tenant_id": tenant_id, "limit": limit}
            )

    @staticmethod
    async def global_overview() -> dict[str, Any]:
        """平台级资源存量（仅超管视角）：租户/账号/Agent/模型/插件。"""
        async with session_scope() as session:
            row = await fetch_one(session, _GLOBAL, {})
        return row or {}

    @staticmethod
    async def tenant_ranking(*, since: datetime, limit: int = 10) -> list[dict[str, Any]]:
        """租户用量排行（仅超管视角）：按区间运行量倒序。"""
        async with session_scope() as session:
            return await fetch_all(
                session, _RANKING, {"since": since, "limit": limit}
            )
