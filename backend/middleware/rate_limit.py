"""
rate_limit - 租户级限流（设计文档 §9.1 ② 配套）

基于 slowapi 的 Limiter，按 tenant_id 维度限流；key 取自认证后 request.state.tenant_id。
"""
from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address


def _tenant_key(request) -> str:
    """限流 key：优先租户 id，回退客户端 IP。"""
    tid = getattr(request.state, "tenant_id", None)
    return tid or get_remote_address(request)


limiter = Limiter(key_func=_tenant_key)
