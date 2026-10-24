"""审计列参数注入：INSERT / UPDATE 前统一取当前操作者。

表按审计列分三类：
- 带用户 + 租户审计列（原 AuditMixin）：`with_tenant=True`；
- 只带用户审计列（全局表，如 agent_role）：`with_tenant=False`；
- 只有 create_at / updated_at：不需要本模块。

DDL 不给审计列建 DEFAULT：漏填要在写库前报错，而不是静默落到 1001/100 让审计失真。
- 请求期：从 app_state 的上下文取当前操作者；
- 非请求期（启动期种子、修数脚本）：调用方显式传 SYSTEM_USER_ID。
"""
from __future__ import annotations

from backend.app_state import get_tenant_id, get_user_id

# 非请求期写入系统数据时显式使用的操作者（主租户超管）
SYSTEM_USER_ID = 1001
SYSTEM_TENANT_ID = 100


def _pick(explicit: int | None, from_ctx: int | None, field: str) -> int:
    """取值优先级：显式传值 > 请求上下文；两者都没有就报错，不做静默兜底。"""
    if explicit is not None:
        return explicit
    if from_ctx is not None:
        return from_ctx
    raise RuntimeError(
        f"{field} 未赋值，且当前没有请求上下文；"
        f"非请求期写入请显式传值（如 {field}=SYSTEM_USER_ID）"
    )


def audit_on_insert(
    *,
    user_id: int | None = None,
    tenant_id: int | None = None,
    with_tenant: bool = True,
) -> dict[str, int]:
    """INSERT 用的审计列参数：创建人与更新人一致，创建租户与更新租户一致。

    返回值直接与业务参数合并后传给 session.execute，例如：
        params = {"tenant_id": 200, **audit_on_insert()}
    """
    actor = _pick(user_id, get_user_id(), "create_user_id")
    params: dict[str, int] = {"create_user_id": actor, "update_user_id": actor}
    if with_tenant:
        tenant = _pick(tenant_id, get_tenant_id(), "create_tenant_id")
        params["create_tenant_id"] = tenant
        params["update_tenant_id"] = tenant
    return params


def audit_on_update(
    *,
    user_id: int | None = None,
    tenant_id: int | None = None,
    with_tenant: bool = True,
) -> dict[str, int]:
    """UPDATE 用的审计列参数。

    没有上下文时返回空字典，库里原值保持不变：后台任务和修数脚本不该冒充操作者。
    """
    params: dict[str, int] = {}
    actor = user_id if user_id is not None else get_user_id()
    if actor is not None:
        params["update_user_id"] = actor
    if with_tenant:
        tenant = tenant_id if tenant_id is not None else get_tenant_id()
        if tenant is not None:
            params["update_tenant_id"] = tenant
    return params


__all__ = [
    "SYSTEM_TENANT_ID",
    "SYSTEM_USER_ID",
    "audit_on_insert",
    "audit_on_update",
]
