"""短期记忆的用户隔离：key 必须带 user 段，身份缺失时宁可不记。

历史问题是 key 只到 `t:{tenant}:session:{thread}`，同租户内 thread_id 撞上就共享上下文。
"""
from typing import Any

import pytest

from backend.app_state import app_state, tenant_id_ctx, user_id_ctx
from backend.common.memory.memory import MemoryStore, _session_key


class _FakeRedis:
    """只实现短期记忆用到的最小接口。"""

    def __init__(self) -> None:
        self.data: dict[str, list[str]] = {}
        self.ttl: dict[str, int] = {}

    async def rpush(self, key: str, value: str) -> int:
        self.data.setdefault(key, []).append(value)
        return len(self.data[key])

    async def expire(self, key: str, seconds: int) -> None:
        self.ttl[key] = seconds

    async def lrange(self, key: str, start: int, end: int) -> list[str]:
        rows = self.data.get(key, [])
        # Redis 的 -limit/-1 语义：取尾部 limit 条
        if start < 0:
            return rows[start:] if end == -1 else rows[start:end]
        return rows[start : end + 1]


@pytest.fixture()
def identity() -> Any:
    """默认以 租户 100 / 用户 1001 运行，用例结束还原上下文。"""
    t = tenant_id_ctx.set(100)
    u = user_id_ctx.set(1001)
    yield
    tenant_id_ctx.reset(t)
    user_id_ctx.reset(u)


@pytest.fixture()
def fake_redis(monkeypatch: pytest.MonkeyPatch) -> _FakeRedis:
    redis = _FakeRedis()
    monkeypatch.setattr(app_state, "redis", redis)
    return redis


def test_session_key_contains_user_segment(identity: None) -> None:
    assert _session_key("abc") == "t:100:u:1001:session:abc"


def test_session_key_is_none_without_identity() -> None:
    """没有用户上下文时不生成 key，避免退化成租户级共享。"""
    user_id_ctx.set(None)
    assert _session_key("abc") is None


async def test_short_memory_not_shared_between_users(
    identity: None, fake_redis: _FakeRedis
) -> None:
    """同一租户、同一 thread_id，不同用户读不到彼此的短期记忆。"""
    store = MemoryStore()
    await store.push_short("thread-1", {"role": "user", "content": "用户1001的隐私"})
    assert await store.get_short("thread-1") == [{"role": "user", "content": "用户1001的隐私"}]

    user_id_ctx.set(1002)
    assert await store.get_short("thread-1") == []
