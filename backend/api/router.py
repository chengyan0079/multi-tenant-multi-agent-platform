"""api 路由装配：把各业务域的路由统一挂到 /api/v1 下。

装配只在这里做一次，业务模块内的 router 只声明资源路径（如 /tenants），
不写版本前缀，避免再次出现 /v1/** 与 /api/v1/** 两种写法并存。

按「谁在访问」分四组挂载，整组仅挂租户上下文依赖；权限判定改由各端点自身的
require_scope 决定（不再按角色拦截）：
- 基建域 /api/v1/admin/**：整组只做装配，无角色守卫；每个端点自行 require_scope，
  超管无租户、不进业务链路（业务域 scope 超管不持有，自然不可见）；
- 业务域 /api/v1/tenant/**：整组挂 require_tenant() 提供租户上下文，超管无租户调用直接 403；
  业务端点各自 require_scope（如 qa:ask、interview:ask 等）；
- 登录态 /api/v1/auth/**：无整组依赖，/login 公开、/menus 与 /me 各自挂 get_current_user；
- 系统域 /api/v1/health、/api/v1/dashboard：直属 /api/v1，不进 admin 组——
  /health 免鉴权（探针无 token），/dashboard 由端点自身 require_scope(DASHBOARD_VIEW) 决定
  （dashboard:view 仅超管角色持有，菜单可见性另用 dashboard:menu 控制）。
模块文件里每个端点都需自挂 require_scope，新增接口务必补上对应 scope。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.api.v1.tenant.agent.exam import router as exam_router
from backend.api.v1.tenant.agent.files import router as files_router
from backend.api.v1.tenant.agent.interview import router as interview_router
from backend.api.v1.tenant.agent.qa import router as qa_router
from backend.api.v1.tenant.agent.qa_results import router as qa_results_router
from backend.api.v1.tenant.agent.qa_sessions import router as qa_sessions_router
from backend.api.v1.tenant.agent.resume import router as resume_router
from backend.api.v1 import dashboard as dashboard_api
from backend.api.v1 import health as health_api
from backend.api.v1.admin import agents as admin_agents
from backend.api.v1.admin import audit as admin_audit
from backend.api.v1.admin import config_center as admin_config
from backend.api.v1.admin import models as admin_models
from backend.api.v1.admin import plugins as admin_plugins
from backend.api.v1.admin import menu as admin_menu
from backend.api.v1.admin import messages as admin_messages
from backend.api.v1.admin import rbac as admin_rbac
from backend.api.v1.admin import tenant as admin_tenant
from backend.api.v1.auth import router as auth_router
from backend.api.v1.tenant.agent import orchestrator
from backend.api.v1.tenant import audit as tenant_audit
from backend.api.v1.tenant import messages as tenant_messages
from backend.api.v1.tenant import roles as tenant_roles
from backend.api.v1.tenant import users as tenant_users
from backend.security.security import (
    require_tenant,
)

API_PREFIX = "/api/v1"
ADMIN_PREFIX = f"{API_PREFIX}/admin"
TENANT_PREFIX = f"{API_PREFIX}/tenant"

# 基建域：Agent 定义与开通策略、插件清单、模型注册表、租户/RBAC/审计
# （后续 tenants/users 也归这组），整组 require_super_admin。
# 注：rbac.router / messages.router 不在此组——读接口对超管+租户管理员开放，写接口仅超管，
# 鉴权混用，单独挂载、由端点自行声明（见 admin/rbac.py / admin/messages.py）。
# config_center.router 同样单独挂载：配置中心为协同流程（所有角色可提交/撤回，
# 仅超管/租户管理员可复核/执行/删除），端点各自 require_scope，不挂整组超管。
_ADMIN = (
    admin_agents.router,
    admin_plugins.router,
    admin_models.router,
    admin_tenant.router,
    admin_menu.router,
    admin_audit.router,
)

# 业务域：会话、编排执行，外加各业务 Agent 的直连入口，以及租户管理员自管的用户/角色/审计，
# 统一收进 /api/v1/tenant/（按 token 鉴权，超管无租户一律 403）。
_BUSINESS = (
    orchestrator.router,
    qa_router,
    qa_results_router,
    qa_sessions_router,
    files_router,
    resume_router,
    exam_router,
    interview_router,
    tenant_users.router,
    tenant_roles.router,
    tenant_audit.router,
    tenant_messages.router,
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
    # 权限仅由 scope 决定（各端点自挂 require_scope）；不再按角色拦截，
    # 否则拿到 scope 的非超管角色会被挡在门外。
    api.include_router(
        _bundle(_ADMIN),
        prefix=ADMIN_PREFIX,
    )
    # RBAC 端点鉴权混用：读接口（角色目录）对超管+租户管理员开放，写接口（覆盖权限点/
    # 新建/删除角色、改任意租户用户角色）仅超管。不挂整组依赖，由各端点显式声明，
    # 否则整组 require_super_admin 会先于接口级依赖执行、把租户管理员挡在角色目录之外。
    api.include_router(
        admin_rbac.router,
        prefix=ADMIN_PREFIX,
    )
    # 消息管理：超管 + 租户管理员（message:view）；端点级 require_scope，不挂整组超管
    api.include_router(
        admin_messages.router,
        prefix=ADMIN_PREFIX,
    )
    # 配置中心：协同流程，端点各自 require_scope（page/view/add/update 所有角色；
    # review/execute/delete 仅超管/租户管理员），不挂整组超管
    api.include_router(
        admin_config.router,
        prefix=ADMIN_PREFIX,
    )
    for router in _BUSINESS:
        api.include_router(
            router,
            prefix=TENANT_PREFIX,
            dependencies=[Depends(require_tenant())],
        )
    # 系统域：/health 免鉴权（探针无 token）；/dashboard 权限由端点自身
    # require_scope(Scope.DASHBOARD_VIEW) 决定（dashboard:view 仅超管角色持有，
    # 菜单可见性另用 dashboard:menu 控制）
    api.include_router(health_api.router, prefix=API_PREFIX)
    api.include_router(
        dashboard_api.router,
        prefix=API_PREFIX,
    )
    # 登录态接口：/login 公开，其余在模块内各自挂 get_current_user
    api.include_router(auth_router.router, prefix=f"{API_PREFIX}/auth")
    return api


api_router = build_api_router()
