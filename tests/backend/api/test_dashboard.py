"""健康检查与监控看板的接口测试。

不连 DB：
- /health 用 fake 客户端注册进 app_state.clients，验证免鉴权与浅/深检查口径；
- /dashboard 用 AsyncMock 替换 DashboardDao 与 RBAC 解析，验证「超管看全局 /
  租户管理员只看本租户 / 普通用户 403 / 跨租户越权 403」四条边界与返回结构。
"""
from __future__ import annotations

import contextlib
import json
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

import jwt
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.exceptions import register_exception_handlers
from backend.api.router import api_router
from backend.app_state import app_state
from backend.data.clients.base import BaseClient
from backend.data.clients.bundle import ClientBundle
from backend.data.dao.business import dashboard_dao

_SECRET = "test-secret-0123456789abcdefghijkl"  # ≥32 字节，避免 PyJWT 密钥长度告警

# 今日 10 次 / 昨日同期 5 次；运行 10 次其中 1 次失败，上一区间 5 次全成功
_STATS = {
    "api_calls_today": 10,
    "api_calls_prev": 5,
    "active_threads": 4,
    "active_threads_prev": 2,
    "runs": 10,
    "error_runs": 1,
    "runs_prev": 5,
    "error_runs_prev": 0,
}
_TREND_TODAY = {"date": datetime.now().strftime("%m-%d"), "requests": 10, "errors": 1}


class _FakeSecurity:
    jwt_secret = _SECRET
    jwt_algorithm = "HS256"
    jwt_expire_minutes = 1440


class _FakeClient(BaseClient):
    """最小可用的中间件客户端替身。"""

    def __init__(self, name: str, connected: bool = True, broken: bool = False) -> None:
        self.name = name
        self._connected = connected
        self._broken = broken

    async def connect(self) -> None:
        self._connected = True

    async def close(self) -> None:
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def health_check(self) -> bool:
        if self._broken:
            raise RuntimeError("probe timeout")
        return self._connected


def _token(user_id: int, tenant_id: int | None = None) -> dict[str, str]:
    payload: dict = {"user_id": user_id}
    if tenant_id is not None:
        payload["tenant_id"] = tenant_id
    raw = jwt.encode(payload, _SECRET, algorithm="HS256")
    return {"Authorization": f"Bearer {raw}"}


def _bundle(*clients: BaseClient) -> ClientBundle:
    bundle = ClientBundle()
    for client in clients:
        bundle.add(client)
    return bundle


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(api_router)
    register_exception_handlers(app)
    return app


# ---------------- /health ----------------


def test_health_without_token_is_public():
    """探针没有 token：必须 200，且能看到各中间件状态。"""
    bundle = _bundle(_FakeClient("postgres"), _FakeClient("redis"))
    with patch.object(app_state, "clients", bundle), patch.object(
        app_state, "started_at", datetime.now() - timedelta(seconds=30)
    ):
        resp = TestClient(_app()).get("/api/v1/health")

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["status"] == "ok"
    assert data["components"] == {"postgres": "up", "redis": "up"}
    assert data["service"]["uptime_s"] >= 30


def test_health_degraded_when_component_down():
    bundle = _bundle(_FakeClient("postgres"), _FakeClient("redis", connected=False))
    with patch.object(app_state, "clients", bundle), patch.object(
        app_state, "started_at", datetime.now()
    ):
        data = TestClient(_app()).get("/api/v1/health").json()["data"]

    assert data["status"] == "degraded"
    assert data["components"]["redis"] == "down"


def test_health_deep_reports_probe_error():
    """深检查下探活抛错要落到组件状态里，不能把 500 冒给探针。"""
    bundle = _bundle(_FakeClient("postgres", broken=True))
    with patch.object(app_state, "clients", bundle), patch.object(
        app_state, "started_at", datetime.now()
    ):
        resp = TestClient(_app()).get("/api/v1/health", params={"deep": "true"})

    assert resp.status_code == 200
    state = resp.json()["data"]["components"]["postgres"]
    assert state.startswith("down: RuntimeError")


# ---------------- /dashboard ----------------


@contextlib.contextmanager
def _dashboard_env(
    *,
    role_name: str,
    tenant_id: int | None,
    trend_rows: list[dict] | None = None,
):
    """构造已登录环境：tenant_id=None 走超管分支，否则走租户分支。"""
    user = {"id": 2001, "username": "u", "name": "u", "tenant_id": tenant_id or 1}
    identity = {"role_name": role_name, "tenant_is_primary": tenant_id is None, "scopes": []}
    rbac_target = (
        "backend.data.dao.auth.rbac_dao.RbacDao.get_super_admin_identity"
        if tenant_id is None
        else "backend.data.dao.auth.rbac_dao.RbacDao.get_identity"
    )

    with patch.object(app_state.settings, "security", _FakeSecurity()), patch(
        rbac_target, new=AsyncMock(return_value=identity)
    ), patch(
        "backend.data.dao.auth.user_dao.UserDao.get", new=AsyncMock(return_value=user)
    ), patch(
        "backend.data.dao.business.dashboard_dao.DashboardDao.stats",
        new=AsyncMock(return_value=_STATS),
    ), patch(
        "backend.data.dao.business.dashboard_dao.DashboardDao.agent_total",
        new=AsyncMock(return_value=3),
    ), patch(
        "backend.data.dao.business.dashboard_dao.DashboardDao.request_trend",
        new=AsyncMock(
            return_value=[_TREND_TODAY] if trend_rows is None else trend_rows
        ),
    ), patch(
        "backend.data.dao.business.dashboard_dao.DashboardDao.agent_distribution",
        new=AsyncMock(return_value=[{"name": "QA 问答", "value": 6}]),
    ), patch(
        "backend.data.dao.business.dashboard_dao.DashboardDao.latency_by_hour",
        new=AsyncMock(return_value=[{"hour": "00", "avg": 120}]),
    ), patch(
        "backend.data.dao.business.dashboard_dao.DashboardDao.recent_activities",
        new=AsyncMock(return_value=[{
            "time": "2026-10-25 10:00:00",
            "user": "admin",
            "action": "登录",
            "target": "-",
            "result": "成功",
        }]),
    ), patch(
        "backend.data.dao.business.dashboard_dao.DashboardDao.global_overview",
        new=AsyncMock(return_value={"tenants": 2, "agents": 4}),
    ), patch(
        "backend.data.dao.business.dashboard_dao.DashboardDao.tenant_ranking",
        new=AsyncMock(return_value=[{"tenant_id": 1, "runs": 5}]),
    ), patch.object(app_state, "started_at", datetime.now()):
        yield TestClient(_app())


def test_dashboard_requires_token():
    assert TestClient(_app()).get("/api/v1/dashboard").status_code == 401


def test_dashboard_rejects_normal_user():
    """普通租户用户（student）不在准入范围。"""
    with _dashboard_env(role_name="student", tenant_id=2) as client:
        resp = client.get("/api/v1/dashboard", headers=_token(2001, 2))
    assert resp.status_code == 403


def test_dashboard_tenant_admin_sees_own_tenant_only():
    with _dashboard_env(role_name="tenant_admin", tenant_id=2) as client:
        resp = client.get("/api/v1/dashboard", headers=_token(2001, 2))

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["scope"] == {
        "is_super_admin": False,
        "tenant_id": 2,
        "days": 7,
        "since": data["scope"]["since"],
    }
    # 租户视角不下发平台级存量与跨租户排行
    assert "global" not in data
    assert "tenant_ranking" not in data
    assert data["agent_distribution"] == [{"name": "QA 问答", "value": 6}]


def test_dashboard_stats_align_frontend():
    """四张卡的口径：同比百分比 + 成功率百分点差。"""
    with _dashboard_env(role_name="tenant_admin", tenant_id=2) as client:
        stats = client.get(
            "/api/v1/dashboard", headers=_token(2001, 2)
        ).json()["data"]["stats"]

    assert [s["key"] for s in stats] == [
        "api_calls", "active_threads", "agents", "success_rate"
    ]
    calls, threads, agents, rate = stats
    # 10 vs 5 → +100%；4 vs 2 → +100%
    assert (calls["value"], calls["trend"]) == (10, 100.0)
    assert (threads["value"], threads["trend"]) == (4, 100.0)
    assert (agents["value"], agents["trend"]) == (3, 0.0)
    # 成功率 90.0%，上一区间 100%，差 -10 个百分点
    assert (rate["value"], rate["suffix"], rate["trend"]) == (90.0, "%", -10.0)


def test_dashboard_trend_fills_missing_days():
    """有数据的天保留，没有的天补 0，保证 7 个点。"""
    with _dashboard_env(role_name="tenant_admin", tenant_id=2) as client:
        trend = client.get(
            "/api/v1/dashboard", headers=_token(2001, 2)
        ).json()["data"]["request_trend"]

    assert len(trend) == 7
    today = trend[-1]
    assert today == {
        "date": datetime.now().strftime("%m-%d"), "requests": 10, "errors": 1
    }
    assert all(p["requests"] == 0 for p in trend[:-1])


def test_dashboard_payload_covers_all_frontend_sections():
    with _dashboard_env(role_name="tenant_admin", tenant_id=2) as client:
        data = client.get("/api/v1/dashboard", headers=_token(2001, 2)).json()["data"]

    for key in (
        "stats", "request_trend", "agent_distribution",
        "latency_by_hour", "recent_activities",
    ):
        assert key in data
    assert data["recent_activities"][0]["result"] == "成功"


def test_dashboard_tenant_admin_cannot_query_other_tenant():
    """显式传别的 tenant_id 必须 403，不能静默忽略参数。"""
    with _dashboard_env(role_name="tenant_admin", tenant_id=2) as client:
        resp = client.get(
            "/api/v1/dashboard", params={"tenant_id": 3}, headers=_token(2001, 2)
        )
    assert resp.status_code == 403


def test_dashboard_super_admin_sees_global_and_ranking():
    with _dashboard_env(role_name="admin", tenant_id=None) as client:
        resp = client.get("/api/v1/dashboard", headers=_token(2001))

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["scope"]["is_super_admin"] is True
    assert data["scope"]["tenant_id"] is None
    assert data["global"] == {"tenants": 2, "agents": 4}
    assert data["tenant_ranking"] == [{"tenant_id": 1, "runs": 5}]


def test_dashboard_super_admin_can_focus_one_tenant():
    """超管指定 tenant_id 时按该租户统计，且不再重复下发全局排行。"""
    with _dashboard_env(role_name="admin", tenant_id=None) as client:
        resp = client.get(
            "/api/v1/dashboard", params={"tenant_id": 7}, headers=_token(2001)
        )

    data = resp.json()["data"]
    assert data["scope"]["tenant_id"] == 7
    assert data["global"] == {"tenants": 2, "agents": 4}
    assert "tenant_ranking" not in data


def test_dashboard_rejects_bad_range():
    with _dashboard_env(role_name="admin", tenant_id=None) as client:
        assert client.get(
            "/api/v1/dashboard", params={"days": 0}, headers=_token(2001)
        ).status_code == 422


def test_dashboard_cache_keys_split_by_role():
    """超管与租户管理员各一份缓存 key，互不串；聚焦租户与全平台也是不同 key。"""
    fake_redis = AsyncMock()
    fake_redis.get.return_value = None  # 始终未命中，触发写入，借机收集 key
    keys: list[str] = []

    async def _capture_set(key, value, ex=None):
        keys.append(key)

    fake_redis.set.side_effect = _capture_set

    with patch.object(app_state, "redis", fake_redis), _dashboard_env(
        role_name="admin", tenant_id=None
    ) as client:
        client.get("/api/v1/dashboard", headers=_token(2001))
    with patch.object(app_state, "redis", fake_redis), _dashboard_env(
        role_name="tenant_admin", tenant_id=2
    ) as client:
        client.get("/api/v1/dashboard", headers=_token(2001, 2))

    assert any("super" in k for k in keys)
    assert any("tenant" in k for k in keys)
    # 超管全平台 + 租户管理员本租户，两个不同 key
    assert len({k for k in keys}) == 2


def test_dashboard_serves_from_cache_on_second_hit():
    """命中缓存后直接返回，不再查 DB（DashboardDao.stats 不再被调用）。"""
    fake_redis = AsyncMock()
    fake_redis.get.return_value = None  # 首次未命中

    with patch.object(app_state, "redis", fake_redis), _dashboard_env(
        role_name="admin", tenant_id=None
    ) as client:
        client.get("/api/v1/dashboard", headers=_token(2001))
        assert fake_redis.set.await_count == 1  # 首次计算后写入

        db_stats = dashboard_dao.DashboardDao.stats
        db_stats.reset_mock()
        # 第二次让缓存命中
        fake_redis.get.return_value = json.dumps(
            {"code": 0, "msg": "", "data": {"stats": [], "scope": {"is_super_admin": True}}}
        )
        resp = client.get("/api/v1/dashboard", headers=_token(2001))

    assert resp.status_code == 200
    assert db_stats.await_count == 0  # 命中缓存，未回源
