"""消费端鉴权：按消息中的 tenant_id / user_id 重新校验，零信任。

broker 本身不做业务鉴权，鉴权在消费端落地——消息可能被重投或（broker 未鉴权时）
被伪造，必须以消费端校验为准。鉴权复用请求期同一套身份解析（RbacService.resolve_identity），
保证 HTTP 入口与 MQ 消费端口径一致。
"""
from __future__ import annotations

from backend.common.logger import logger
from backend.observability.exception import BizException, ErrCode
from backend.security.rbac import RbacService


async def authorize_task(
    user_id: int,
    tenant_id: int | None,
    required_scopes: list[str],
) -> None:
    """校验消息发起者有权在 tenant_id 下执行 required_scopes 对应的动作。

    - user_id == 0：系统 / 超管内部任务，放行；
    - 其余走 RbacService.resolve_identity 解析身份（含租户归属与 scopes）；
    - 身份不存在（用户不在该租户 / 角色脏数据）或缺少所需 scope → 拒绝。
    不通过抛 BizException，由 consumer 捕获后直接 ack（不执行、不重投）。
    """
    if user_id == 0:
        return
    identity = await RbacService.resolve_identity(user_id, tenant_id)
    if identity is None:
        raise BizException(
            ErrCode.FORBIDDEN,
            f"消息鉴权失败：用户 {user_id} 在租户 {tenant_id} 无身份",
        )
    if identity.is_super_admin:
        return
    missing = [s for s in required_scopes if s not in identity.scopes]
    if missing:
        logger.warning(f"消息鉴权失败 user={user_id} tenant={tenant_id} 缺 {missing}")
        raise BizException(ErrCode.FORBIDDEN, f"消息鉴权失败：缺少权限点 {missing}")
