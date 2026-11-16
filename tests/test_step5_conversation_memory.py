"""Step 5 单测：会话服务与记忆（§5.2 / §5.8）。

覆盖：UnifiedConversationService.append_turn / load_context / append_long_term，
MemoryStore 短期记忆 Pydantic 往返，LongTermMemoryDao.list_recent 返回具体对象（D17）。
全部用内存 fake，不依赖真实 PG / Redis；并验证 Redis / PG 异常时的降级（不抛、不改成功语义）。
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import pytest

from backend.app_state import app_state
from backend.orchestration.agent_spec import AgentSpec
from backend.orchestration.unified_schemas import LongTermMemoryBlock, ShortTermTurn
from backend.services.long_term_memory_extractor import LongTermMemoryExtractor
from backend.services.unified_conversation import (
    ConversationContext,
    UnifiedConversationService,
)


# --------------------------------------------------------------------------- #
# 内存 fake
# --------------------------------------------------------------------------- #
class FakeTurnDao:
    def __init__(self) -> None:
        self.rows: list[Any] = []
        self.append_errors = 0

    async def append(self, *, row: Any) -> str:
        tid = str(uuid4())
        # 保存一份快照以便断言
        saved = row.model_copy()
        saved.id = tid
        self.rows.append(saved)
        return tid

    async def list_recent_by_thread(self, *, thread_id, tenant_id, user_id, limit=200):
        return [r for r in self.rows if r.thread_id == thread_id]


class FakeMemoryStore:
    def __init__(self) -> None:
        self.data: dict[str, list[ShortTermTurn]] = {}
        self.raise_on_push = False

    async def push_short(self, thread_id: str, message: ShortTermTurn) -> None:
        if self.raise_on_push:
            raise RuntimeError("redis down")
        self.data.setdefault(thread_id, []).append(message)

    async def get_short(self, thread_id: str, limit: int = 20) -> list[ShortTermTurn]:
        items = self.data.get(thread_id, [])
        return items[-limit:]


class FakeLongTermDao:
    def __init__(self) -> None:
        self.blocks: list[LongTermMemoryBlock] = []

    async def append(self, *, tenant_id, user_id, agent_id, block, content, embedding_id=""):
        self.blocks.append(
            LongTermMemoryBlock(
                id=str(uuid4()),
                agent_id=agent_id,
                block=block,
                content=content,
                embedding_id=embedding_id,
            )
        )

    async def list_recent(self, *, tenant_id, user_id, agent_id, block=None, limit=50):
        out = [b for b in self.blocks if b.agent_id == agent_id]
        if block:
            out = [b for b in out if b.block == block]
        return out


def _spec() -> AgentSpec:
    return AgentSpec(
        agent_type="qa",
        short_term_limit=5,
        long_term_blocks=("summary", "fact", "preference"),
    )


# --------------------------------------------------------------------------- #
# 服务：append_turn 写 turn + 短期记忆
# --------------------------------------------------------------------------- #
def test_append_turn_writes_turn_and_short_memory() -> None:
    turn_dao = FakeTurnDao()
    mem = FakeMemoryStore()
    svc = UnifiedConversationService(
        turn_dao=turn_dao, memory_store=mem, long_term_dao=FakeLongTermDao()
    )
    tid = asyncio.run(
        svc.append_turn(
            thread_id="U1",
            tenant_id=1,
            user_id=2,
            agent_type="qa",
            spec_version="1.0.0",
            trace_id="tr-1",
            turn_index=1,
            event_type="token",
            user_content="怎么用 LangGraph 做检查点？",
            assistant_content="用 AsyncPostgresSaver。",
        )
    )
    assert tid != "local"
    assert len(turn_dao.rows) == 1
    assert turn_dao.rows[0].user_content == "怎么用 LangGraph 做检查点？"
    assert len(mem.data["U1"]) == 1
    assert mem.data["U1"][0].role == "user"
    assert mem.data["U1"][0].agent_type == "qa"
    assert mem.data["U1"][0].event_type == "token"


def test_append_turn_degrades_when_memory_raises() -> None:
    turn_dao = FakeTurnDao()
    mem = FakeMemoryStore()
    mem.raise_on_push = True
    svc = UnifiedConversationService(
        turn_dao=turn_dao, memory_store=mem, long_term_dao=FakeLongTermDao()
    )
    # Redis 异常不应中断主链路，turn 仍写回
    tid = asyncio.run(
        svc.append_turn(
            thread_id="U1",
            tenant_id=1,
            user_id=2,
            agent_type="qa",
            spec_version="1.0.0",
            trace_id="tr-1",
            turn_index=2,
            event_type="token",
            assistant_content="ok",
        )
    )
    assert len(turn_dao.rows) == 1
    assert tid != "local"


# --------------------------------------------------------------------------- #
# 服务：load_context 装配短期 + 长期 + 摘要
# --------------------------------------------------------------------------- #
def test_load_context_assembles_short_and_long() -> None:
    mem = FakeMemoryStore()
    mem.data["U1"] = [
        ShortTermTurn(turn_id="t1", role="user", content="上周的偏好", agent_type="qa"),
        ShortTermTurn(turn_id="t2", role="assistant", content="已记下", agent_type="qa"),
    ]
    long_dao = FakeLongTermDao()
    asyncio.run(
        long_dao.append(
            tenant_id=1, user_id=2, agent_id="qa", block="preference", content="偏好后端"
        )
    )
    svc = UnifiedConversationService(turn_dao=FakeTurnDao(), memory_store=mem, long_term_dao=long_dao)
    ctx: ConversationContext = asyncio.run(
        svc.load_context(
            thread_id="U1",
            tenant_id=1,
            user_id=2,
            spec=_spec(),
            existing_summary="历史摘要",
        )
    )
    assert ctx.existing_summary == "历史摘要"
    assert len(ctx.short_term) == 2
    assert ctx.short_term[0].content == "上周的偏好"
    assert len(ctx.long_term) == 1
    assert ctx.long_term[0].block == "preference"
    assert ctx.long_term[0].content == "偏好后端"


# --------------------------------------------------------------------------- #
# 服务：append_long_term 抽取 + 写入
# --------------------------------------------------------------------------- #
def test_append_long_term_extracts_and_stores() -> None:
    long_dao = FakeLongTermDao()

    async def fake_extract(*, agent_id, summary, turns):
        return [
            LongTermMemoryBlock(agent_id=agent_id, block="summary", content=summary or ""),
            LongTermMemoryBlock(agent_id=agent_id, block="fact", content="用户是后端"),
        ]

    extractor = LongTermMemoryExtractor(extract_fn=fake_extract)
    svc = UnifiedConversationService(
        turn_dao=FakeTurnDao(), memory_store=FakeMemoryStore(), long_term_dao=long_dao, extractor=extractor
    )
    asyncio.run(
        svc.append_long_term(
            tenant_id=1,
            user_id=2,
            agent_id="qa",
            summary="一期总结",
            turns=[ShortTermTurn(turn_id="t1", role="user", content="x")],
        )
    )
    assert len(long_dao.blocks) == 2
    assert {b.block for b in long_dao.blocks} == {"summary", "fact"}


# --------------------------------------------------------------------------- #
# MemoryStore 真实短期记忆 Pydantic 往返（用 FakeRedis + 打桩租户/用户上下文）
# --------------------------------------------------------------------------- #
class FakeRedis:
    def __init__(self) -> None:
        self.data: dict[str, list[str]] = {}

    async def rpush(self, key: str, val: str) -> None:
        self.data.setdefault(key, []).append(val)

    async def expire(self, key: str, ttl: int) -> None:
        pass

    async def lrange(self, key: str, start: int, end: int) -> list[str]:
        items = self.data.get(key, [])

        def _slice(s: int, e: int) -> list[str]:
            n = len(items)
            if s < 0:
                s = max(0, n + s)
            if e < 0:
                e = n + e
            return items[s : e + 1]

        return _slice(start, end)


def test_memory_store_short_roundtrip_pydantic(monkeypatch) -> None:
    from backend.common.memory import memory as memory_mod

    monkeypatch.setattr(memory_mod, "get_tenant_id", lambda: 1)
    monkeypatch.setattr(memory_mod, "get_user_id", lambda: 2)
    app_state.redis = FakeRedis()

    turn = ShortTermTurn(
        turn_id="t1",
        role="user",
        content="怎么用 LangGraph 做检查点？",
        agent_type="qa",
        event_type="token",
        create_at=datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc),
    )
    store = memory_mod.MemoryStore()
    asyncio.run(store.push_short("U1", turn))
    got = asyncio.run(store.get_short("U1", limit=20))
    assert len(got) == 1
    assert got[0] == turn


def test_memory_store_skips_when_no_tenant_context(monkeypatch) -> None:
    from backend.common.memory import memory as memory_mod

    monkeypatch.setattr(memory_mod, "get_tenant_id", lambda: None)
    monkeypatch.setattr(memory_mod, "get_user_id", lambda: None)
    app_state.redis = FakeRedis()

    store = memory_mod.MemoryStore()
    # 缺租户/用户上下文时跳过写入，绝不跨用户共享
    asyncio.run(
        store.push_short(
            "U1",
            ShortTermTurn(turn_id="t1", role="user", content="x", agent_type="qa"),
        )
    )
    assert app_state.redis.data == {}


def test_unified_turn_dao_insert_includes_audit_columns() -> None:
    """agent_unified_turn 带 4 个 AuditMixin NOT NULL 列，INSERT 必须显式写入，
    且值由归属用户/租户派生（与 qa_result_dao 等现有 raw DAO 一致）。"""
    from backend.data.dao.agent.unified_turn_dao import UnifiedTurnDao, UnifiedTurnRow, _INSERT

    assert "create_user_id" in _INSERT.text and "update_user_id" in _INSERT.text
    assert "create_tenant_id" in _INSERT.text and "update_tenant_id" in _INSERT.text

    row = UnifiedTurnRow(
        tenant_id=1,
        user_id=2,
        thread_id="U1",
        turn_index=1,
        agent_type="qa",
        event_type="token",
        user_content="x",
    )
    params = UnifiedTurnDao._build_insert_params(row=row)
    assert params["create_user_id"] == 2 and params["update_user_id"] == 2
    assert params["create_tenant_id"] == 1 and params["update_tenant_id"] == 1
    # JSON 列已序列化为字符串（::json 绑定）
    assert isinstance(params["payload"], str) and isinstance(params["routing"], str)
