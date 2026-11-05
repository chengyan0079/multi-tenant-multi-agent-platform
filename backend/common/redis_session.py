"""登录会话的 Redis 层（滑动续期 + 登出失效）。

JWT 仍是身份载体（token 单源不变）；这里只管「会话是否仍有效」与 TTL：
- 登录写 `auth:session:{jti}`，TTL 取 SESSION_TTL_SECONDS（默认 900s = 15 分钟）；
- 每次成功请求 EXPIRE 重置 TTL（滑动续期，token 本身不变、前端无感）；
- 登出 DELETE 该 key，立即失效。

jti 缺失的旧 token（本功能上线前签发的）不查 Redis，兼容到期。Redis 不可用时
所有函数静默放行，退化成纯 JWT 验签，不阻断业务。
"""
from __future__ import annotations

import json
from typing import Optional

from backend.app_state import app_state
from backend.common.logger import get_logger

logger = get_logger("session")

_KEY_PREFIX = "auth:session:"


def _key(jti: str) -> str:
    return f"{_KEY_PREFIX}{jti}"


def _ttl() -> int:
    """会话 TTL（秒），来自配置，缺省 900。"""
    try:
        return app_state.settings.security.session_ttl_seconds
    except Exception:  # noqa: BLE001
        return 900


async def create_session(jti: str, user_id: int, tenant_id: Optional[int]) -> None:
    """登录成功后写会话；Redis 不可用时静默跳过（退化成纯 JWT 验签）。"""
    r = app_state.redis
    if r is None:
        return
    try:
        await r.set(
            _key(jti),
            json.dumps({"user_id": user_id, "tenant_id": tenant_id}),
            ex=_ttl(),
        )
    except Exception:  # noqa: BLE001
        logger.warning("写入登录会话失败（跳过 Redis 会话控制）")


async def touch_session(jti: str) -> bool:
    """续期：重置 TTL 为配置值。返回 key 是否仍存在（False 表示已登出/过期）。"""
    r = app_state.redis
    if r is None:
        return True  # 无 Redis 时放行，不阻断
    try:
        # expire 对不存在的 key 返回 0，借此判断会话是否仍有效
        ok = await r.expire(_key(jti), _ttl())
        return bool(ok)
    except Exception:  # noqa: BLE001
        logger.warning("续期失败（放行本次请求）")
        return True


async def delete_session(jti: str) -> None:
    """登出：删除会话 key。"""
    r = app_state.redis
    if r is None:
        return
    try:
        await r.delete(_key(jti))
    except Exception:  # noqa: BLE001
        logger.warning("删除登录会话失败")


async def delete_sessions_by_tenant(tenant_id: int) -> int:
    """按租户批量强踢：扫描所有会话，删除 value.tenant_id == tenant_id 的 key。

    会话 value 为 {"user_id":..., "tenant_id":...}，超管会话 tenant_id=None 不会误删。
    Redis 不可用时静默返回 0（退化成鉴权侧 enabled 拦截）。
    """
    r = app_state.redis
    if r is None:
        return 0
    count = 0
    try:
        cursor = 0
        while True:
            cursor, keys = await r.scan(cursor=cursor, match=f"{_KEY_PREFIX}*", count=200)
            if keys:
                values = await r.mget(*keys)
                to_del = [
                    k
                    for k, v in zip(keys, values)
                    if v and _safe_load(v).get("tenant_id") == tenant_id
                ]
                if to_del:
                    await r.delete(*to_del)
                    count += len(to_del)
            if cursor == 0:
                break
    except Exception:  # noqa: BLE001
        logger.warning("按租户批量删除会话失败")
    return count


def _safe_load(v: "bytes | str") -> dict:
    try:
        return json.loads(v)
    except Exception:  # noqa: BLE001
        return {}
