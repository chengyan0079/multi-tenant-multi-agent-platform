"""租户级限流：基于 slowapi，按 tenant_id 维度限流（回退 IP）。"""

from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address


def _tenant_key(request) -> str:
    """限流 key：优先租户 id，回退客户端 IP。"""
    tid = getattr(request.state, "tenant_id", None)
    return tid or get_remote_address(request)


limiter = Limiter(key_func=_tenant_key)
