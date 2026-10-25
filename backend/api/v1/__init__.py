"""api/v1 包：按业务域组织的 HTTP 端点。

所有端点统一挂在 /api/v1 前缀下（装配见 backend/api/router.py），
包内模块只声明资源路径，不写版本前缀。

tenant/agent/  Agent 编排执行端点（业务域，挂在 /api/v1/tenant/ 下）
tenant/chat/   会话域：统一入口、线程状态、人工队列（同上）
config/   配置域（配置中心审批流）
auth/     登录、租户切换、菜单下发
admin/    超管域：租户、RBAC、审计、配置、模型
tenant/   租户管理员域：本租户用户与角色、审计

规划中的域按 chat/ 的方式建模块（`<域>/<资源>.py` 暴露 router），
实现后在 router.py 里并入对应的元组。
"""
