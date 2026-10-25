"""api 路由装配：把各业务域的路由统一挂到 /api/v1 下。

装配只在这里做一次，业务模块内的 router 只声明资源路径（如 /tenants），
不写版本前缀，避免再次出现 /v1/** 与 /api/v1/** 两种写法并存。

按「谁在访问」分四组挂载，鉴权依赖也只在装配处挂一次：
- 基建域 /api/v1/admin/**：整组 require_super_admin()，超管无租户、不进业务链路；
- 业务域 /api/v1/tenant/**：整组 require_tenant()，超管调用直接 403；
- 登录态 /api/v1/auth/**：无整组依赖，/login 公开、/menus 与 /me 各自挂 get_current_user；
- 系统域 /api/v1/health、/api/v1/dashboard：直属 /api/v1，不进 admin 组——
  /health 必须免鉴权（探针无 token，挂 super_admin 会直接 403），
  /dashboard 挂 require_admin_or_tenant_admin（超管全局 / 租户管理员本租户）。
模块文件里不再重复写鉴权，新增接口漏挂的可能性就没有了。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.agents.exam.api import router as exam_router
from backend.agents.interview.api import router as interview_router
from backend.agents.qa.api import router as qa_router
from backend.agents.resume.api import router as resume_router
from backend.api.v1 import dashboard as dashboard_api
from backend.api.v1 import health as health_api
from backend.api.v1.admin import agents as admin_agents
from backend.api.v1.admin import audit as admin_audit
from backend.api.v1.admin import config_center as admin_config
from backend.api.v1.admin import models as admin_models
from backend.api.v1.admin import plugins as admin_plugins
from backend.api.v1.admin import menu as admin_menu
from backend.api.v1.admin import rbac as admin_rbac
from backend.api.v1.admin import tenant as admin_tenant
from backend.api.v1.auth import router as auth_router
from backend.api.v1.tenant.agent import orchestrator
from backend.api.v1.tenant.chat import escalations, threads, unified
from backend.api.v1.tenant import audit as tenant_audit
from backend.api.v1.tenant import roles as tenant_roles
from backend.api.v1.tenant import users as tenant_users
from backend.security.security import (
    require_admin_or_tenant_admin,
    require_super_admin,
    require_tenant,
)

API_PREFIX = "/api/v1"
ADMIN_PREFIX = f"{API_PREFIX}/admin"
TENANT_PREFIX = f"{API_PREFIX}/tenant"

# 基建域：Agent 定义与开通策略、插件清单、配置中心审批流、模型注册表、租户/RBAC/审计
# （后续 tenants/users 也归这组），整组 require_super_admin。
_ADMIN = (
    admin_agents.router,
    admin_plugins.router,
    admin_config.router,
    admin_models.router,
    admin_tenant.router,
    admin_rbac.router,
    admin_menu.router,
    admin_audit.router,
)

# 业务域：会话、编排执行，外加各业务 Agent 的直连入口，以及租户管理员自管的用户/角色/审计，
# 统一收进 /api/v1/tenant/（按 token 鉴权，超管无租户一律 403）。
_BUSINESS = (
    orchestrator.router,
    unified.router,
    threads.router,
    escalations.router,
    qa_router,
    resume_router,
    exam_router,
    interview_router,
    tenant_users.router,
    tenant_roles.router,
    tenant_audit.router,
)


def _bundle(routers: tuple[APIRouter, ...]) -> APIRouter:
    """把一组 router 合成一个，便于统一挂前缀和依赖。"""
    merged = APIRouter()
    for router in routers:
        merged.include_router(router)
    return merged


def build_api_router() -> APIRouter:
    """返回挂好 /api/v1 前缀的总路由。"""
    api = APIRouter()
    api.include_router(
        _bundle(_ADMIN),
        prefix=ADMIN_PREFIX,
        dependencies=[Depends(require_super_admin())],
    )
    for router in _BUSINESS:
        api.include_router(
            router,
            prefix=TENANT_PREFIX,
            dependencies=[Depends(require_tenant())],
        )
    # 系统域：/health 免鉴权（探针无 token），/dashboard 限超管或租户管理员
    api.include_router(health_api.router, prefix=API_PREFIX)
    api.include_router(
        dashboard_api.router,
        prefix=API_PREFIX,
        dependencies=[Depends(require_admin_or_tenant_admin())],
    )
    # 登录态接口：/login 公开，其余在模块内各自挂 get_current_user
    api.include_router(auth_router.router, prefix=f"{API_PREFIX}/auth")
    return api


api_router = build_api_router()
