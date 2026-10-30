"""监控看板端点（/api/v1/dashboard）。

准入：平台超管或租户管理员（装配处挂 require_admin_or_tenant_admin）。
数据范围严格二分，不做隐式降级：
- 超管无租户上下文（tenant_id=None）→ 全平台；传 tenant_id 则聚焦该租户；
- 租户管理员 → 只能是本租户；显式传其他 tenant_id 直接 403，
  而不是静默忽略，避免前端以为自己切到了别的租户却看到本租户数据。

返回结构按前端 Dashboard 页的 5 个区块组织（stats / request_trend /
agent_distribution / latency_by_hour / recent_activities），字段名与页面 dataIndex 对齐，
前端不再需要 mock。`global` / `tenant_ranking` 是超管附加信息，前端未用，留给管理侧排障。
"""
from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.encoders import jsonable_encoder

from backend.app_state import app_state
from backend.common.logger import get_logger
from backend.common.response import success
from backend.data.dao.business.dashboard_dao import DashboardDao
from backend.middleware.auth import CurrentUser, get_current_user

logger = get_logger("dashboard")

# 看板聚合跨多张增长型大表，按角色各缓存一份，一小时 TTL：
# 看板是运营快照，天然容忍小时级延迟；缓存把 DB 压力降到「每小时每 (角色, 租户, 天数) 一次」
DASHBOARD_CACHE_TTL = 3600


def _dashboard_cache_key(role: str, tenant_id: int | None, days: int) -> str:
    """缓存 key 按角色维度拆分：超管与租户管理员各一份，避免两类数据互相串。

    同角色下再按 (租户, 区间天数) 区分；超管聚焦某租户与全平台也是不同 key。
    """
    scope = tenant_id if tenant_id is not None else "all"
    return f"dashboard:v1:{role}:{scope}:{days}"


router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def _pct(current: int | float, previous: int | float) -> float:
    """环比百分比；上一周期为 0 时无对比基准，返回 0 而不是无穷大。"""
    if not previous:
        return 0.0
    return round((current - previous) / previous * 100, 1)


def _fill_trend(
    rows: list[dict[str, Any]], *, days: int, today: date
) -> list[dict[str, Any]]:
    """按天补齐区间，缺数据的天填 0（否则前端折线会断点）。"""
    found = {r["date"]: r for r in rows}
    start = today - timedelta(days=days - 1)
    out: list[dict[str, Any]] = []
    for i in range(days):
        key = (start + timedelta(days=i)).strftime("%m-%d")
        row = found.get(key)
        out.append({
            "date": key,
            "requests": int(row["requests"]) if row else 0,
            "errors": int(row["errors"]) if row else 0,
        })
    return out


@router.get("", summary="监控看板（超管全局 / 租户管理员本租户）")
async def dashboard(
    days: int = Query(7, ge=1, le=90, description="统计区间（天）"),
    tenant_id: Optional[int] = Query(
        None, description="仅超管有效：聚焦某租户；不传为全平台"
    ),
    current: CurrentUser = Depends(get_current_user),  # noqa: B008
) -> Any:
    # 角色准入由装配处 require_admin_or_tenant_admin 保证：超管看全平台，
    # 租户管理员只看本租户（下面的 tenant_id 校验兜住越权）
    if current.is_super_admin:
        scope_tenant = tenant_id
    else:
        if tenant_id is not None and tenant_id != current.tenant_id:
            raise HTTPException(status_code=403, detail="仅可查看本租户数据")
        scope_tenant = current.tenant_id

    role = "super" if current.is_super_admin else "tenant"
    cache_key = _dashboard_cache_key(role, scope_tenant, days)

    # 旁路缓存：命中直接返回；redis 未就绪或读取异常都回源 DB，绝不影响看板可用性
    redis = app_state.redis
    if redis is not None:
        try:
            cached = await redis.get(cache_key)
            if cached:
                return success(json.loads(cached))
        except Exception:
            logger.warning("dashboard 缓存读取失败，回源 DB", exc_info=True)

    today = datetime.now().date()
    since = datetime.combine(today - timedelta(days=days - 1), time.min)
    # 上一区间与当前区间等长，用于「较昨日/上一周期」的环比
    prev_since = since - timedelta(days=days)

    raw = await DashboardDao.stats(
        tenant_id=scope_tenant, since=since, prev_since=prev_since
    )
    agent_total = await DashboardDao.agent_total(tenant_id=scope_tenant)

    api_today = int(raw.get("api_calls_today") or 0)
    api_prev = int(raw.get("api_calls_prev") or 0)
    threads = int(raw.get("active_threads") or 0)
    threads_prev = int(raw.get("active_threads_prev") or 0)
    runs = int(raw.get("runs") or 0)
    error_runs = int(raw.get("error_runs") or 0)
    runs_prev = int(raw.get("runs_prev") or 0)
    error_runs_prev = int(raw.get("error_runs_prev") or 0)

    success_rate = round((runs - error_runs) / runs * 100, 1) if runs else 100.0
    success_rate_prev = (
        round((runs_prev - error_runs_prev) / runs_prev * 100, 1) if runs_prev else 100.0
    )

    stats = [
        {
            "key": "api_calls",
            "title": "今日调用量",
            "value": api_today,
            "suffix": "次",
            "precision": 0,
            "trend": _pct(api_today, api_prev),
        },
        {
            "key": "active_threads",
            "title": "活跃会话",
            "value": threads,
            "suffix": "个",
            "precision": 0,
            "trend": _pct(threads, threads_prev),
        },
        {
            "key": "agents",
            "title": "智能体总数",
            "value": agent_total,
            "suffix": "个",
            "precision": 0,
            # 存量指标没有自然的环比口径，给 0 让前端统一渲染
            "trend": 0.0,
        },
        {
            "key": "success_rate",
            "title": "平均成功率",
            "value": success_rate,
            "suffix": "%",
            "precision": 1,
            # 成功率本身是百分比，环比用「百分点差」而非相对变化
            "trend": round(success_rate - success_rate_prev, 1),
        },
    ]

    started_at = app_state.started_at
    data: dict[str, Any] = {
        "scope": {
            "is_super_admin": current.is_super_admin,
            "tenant_id": scope_tenant,
            "days": days,
            "since": since.isoformat(sep=" ", timespec="seconds"),
        },
        "service": {
            "name": app_state.settings.service.name,
            "version": app_state.settings.service.version,
            "env": app_state.settings.app_env,
            "uptime_s": round((datetime.now() - started_at).total_seconds(), 3)
            if started_at
            else None,
        },
        "stats": stats,
        "request_trend": _fill_trend(
            await DashboardDao.request_trend(tenant_id=scope_tenant, since=since),
            days=days,
            today=today,
        ),
        "agent_distribution": await DashboardDao.agent_distribution(
            tenant_id=scope_tenant, since=since
        ),
        "latency_by_hour": await DashboardDao.latency_by_hour(
            tenant_id=scope_tenant, since=since
        ),
        "recent_activities": await DashboardDao.recent_activities(
            tenant_id=scope_tenant
        ),
    }

    # 平台级存量与租户排行只对超管下发；聚焦某租户时不再重复给全平台排行
    if current.is_super_admin:
        data["global"] = await DashboardDao.global_overview()
        if tenant_id is None:
            data["tenant_ranking"] = await DashboardDao.tenant_ranking(since=since)

    # 旁路写入缓存（一小时 TTL）。序列化前用 jsonable_encoder 兜底 Decimal/datetime，
    # 否则原生 json.dumps 会因 AVG() 返回的 Decimal 抛错
    if redis is not None:
        try:
            await redis.set(
                cache_key, json.dumps(jsonable_encoder(data)), ex=DASHBOARD_CACHE_TTL
            )
        except Exception:
            logger.warning("dashboard 缓存写入失败（不影响返回）", exc_info=True)

    return success(data)
