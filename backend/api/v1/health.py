"""健康检查端点（/api/v1/health，免鉴权）。

为什么放在 /api/v1 根下而不是 /api/v1/admin 下：
admin 路由组在装配处整组挂 require_super_admin()，探针（K8s liveness / 网关心跳 /
负载均衡健康检查）没有 token，放到 admin 下会被鉴权直接挡成 401/403，探针永远失败。
本端点不声明任何鉴权依赖，也不在 admin bundle 内。

默认只回报已注册客户端的连接态（零网络 IO，可被探针高频调用）；
?deep=true 才逐个调用 client.health_check() 做真实探活（SELECT 1 / PING），供排障使用。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Query

from backend.app_state import app_state
from backend.common.response import success

router = APIRouter(tags=["system"])


async def _component_state(name: str, deep: bool) -> str:
    """单个组件的健康态：浅检查看连接态，深检查发真实探活请求。"""
    client = app_state.clients.get(name)
    if not deep:
        return "up" if client.is_connected else "down"
    try:
        return "up" if await client.health_check() else "down"
    except Exception as exc:  # noqa: BLE001 - 探活失败要如实回报，不能把异常冒泡成 500
        return f"down: {type(exc).__name__}: {exc}"


@router.get("/health", summary="健康检查（免鉴权）")
async def health(
    deep: bool = Query(False, description="true=对中间件做真实探活（SELECT 1 / PING）"),
) -> Any:
    """返回服务基本身份与各中间件健康态。

    始终返回 HTTP 200，健康度放在 data.status（ok / degraded）里：
    探针只关心进程是否活着，依赖未就绪属于 degraded，不应让编排系统反复重启进程。
    """
    components: dict[str, str] = {}
    for name in app_state.clients.names():
        components[name] = await _component_state(name, deep)

    now = datetime.now()
    started_at = app_state.started_at
    uptime_s = round((now - started_at).total_seconds(), 3) if started_at else None

    # 没有注册任何客户端说明启动未完成（或仅有 HTTP 层），按未就绪处理
    healthy = bool(components) and all(v == "up" for v in components.values())
    svc = app_state.settings.service

    return success(
        {
            "status": "ok" if healthy else "degraded",
            "service": {
                "name": svc.name,
                "version": svc.version,
                "env": app_state.settings.app_env,
                "started_at": started_at.isoformat(sep=" ", timespec="seconds")
                if started_at
                else None,
                "uptime_s": uptime_s,
            },
            "components": components,
            "time": now.isoformat(sep=" ", timespec="seconds"),
        }
    )
