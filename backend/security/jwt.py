"""JWT 签发（登录响应用，见设计文档 §3）。

token 是唯一身份来源：普通用户/租户管理员含 user_id + tenant_id，平台超管只含 user_id。
验签与解析在 middleware/auth.py（只用 HS256 + JWT_SECRET，不读任何请求头）。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
import secrets

from backend.app_state import app_state


def create_access_token(
    user_id: int,
    tenant_id: int | None = None,
    expire_minutes: int | None = None,
    jti: str | None = None,
) -> str:
    """签发 JWT：默认有效期取配置 JWT_EXPIRE_MINUTES。

    超管 tenant_id=None，token 不携带租户——这是能力上限，业务接口一律 403。
    jti 是会话唯一标识，登录时由调用方生成并写入 Redis 会话层（滑动续期/登出失效用）。
    """
    cfg = app_state.settings.security
    expire = expire_minutes if expire_minutes is not None else cfg.jwt_expire_minutes
    payload: dict[str, Any] = {
        "user_id": user_id,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=expire),
        "jti": jti or secrets.token_hex(16),
    }
    if tenant_id is not None:
        payload["tenant_id"] = tenant_id
    return jwt.encode(payload, cfg.jwt_secret, algorithm=cfg.jwt_algorithm)
