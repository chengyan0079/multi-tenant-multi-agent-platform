"""api 路由装配：把各业务域的路由统一挂到 /api/v1 下。

装配只在这里做一次，业务模块内的 router 只声明资源路径（如 /agents），
不写版本前缀，避免再次出现 /v1/** 与 /api/v1/** 两种写法并存。

按「谁在访问」分两组挂载，鉴权依赖也只在装配处挂一次：
- 基建域 /api/v1/admin/**：整组 require_super_admin()，超管无租户、不进业务链路；
- 业务域 /api/v1/**：整组 require_tenant()，超管调用直接 403。
模块文件里不再重复写鉴权，新增接口漏挂的可能性就没有了。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.agents.exam.api import router as exam_router
from backend.agents.interview.api import router as interview_router
from backend.agents.qa.api import router as qa_router
from backend.agents.resume.api import router as resume_router
from backend.api.v1.admin import agents as admin_agents
from backend.api.v1.admin import config_center as admin_config
from backend.api.v1.admin import plugins as admin_plugins
from backend.api.v1.agent import orchestrator
from backend.api.v1.chat import escalations, threads, unified
from backend.security.security import require_super_admin, require_tenant

API_PREFIX = "/api/v1"
ADMIN_PREFIX = f"{API_PREFIX}/admin"

# 基建域：Agent 定义与开通策略、插件清单、配置中心审批流（后续 models/tenants/users 也归这组）
_ADMIN = (admin_agents.router, admin_plugins.router, admin_config.router)

# 业务域：会话、编排执行，外加各业务 Agent 的直连入口
# （各业务 Agent 的 api.py 留在 backend/agents/ 下，与实现同包）
_BUSINESS = (
    orchestrator.router,
    unified.router,
    threads.router,
    escalations.router,
    qa_router,
    resume_router,
    exam_router,
    interview_router,
)


def _bundle(routers: tuple[APIRouter, ...]) -> APIRouter:
    """把一组 router 合成一个，便于统一挂前缀和依赖。"""
    merged = APIRouter()
    for router in routers:
        merged.include_router(router)
    return merged


def build_api_router() -> APIRouter:
    """返回挂好 /api/v1 前缀的总路由，admin 组额外挂超管校验。"""
    api = APIRouter()
    api.include_router(
        _bundle(_ADMIN),
        prefix=ADMIN_PREFIX,
        dependencies=[Depends(require_super_admin())],
    )
    for router in _BUSINESS:
        api.include_router(
            router,
            prefix=API_PREFIX,
            dependencies=[Depends(require_tenant())],
        )
    return api


api_router = build_api_router()
