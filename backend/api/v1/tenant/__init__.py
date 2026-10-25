"""tenant - 租户管理员域（/api/v1/tenant/**）：本租户用户与角色、审计。

整组在 api/router.py 装配处统一挂 require_tenant()，模块内再按接口叠加 require_tenant_admin()
与 require_scope——超管没有租户上下文，会被 require_tenant 直接挡在门外。
"""
