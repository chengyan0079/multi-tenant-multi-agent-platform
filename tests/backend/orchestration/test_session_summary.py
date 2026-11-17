"""统一入口会话摘要测试：读取注入、触发条件、压缩失败降级。"""
from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from backend.orchestration.unified_graph import UnifiedGraph


@pytest.mark.asyncio
async def test_load_summary_degrades_to_none_on_db_error():
    """DAO 抛错时降级为 None，不影响主链路。"""
    import backend.data.dao.agent.unified_turn_dao as dao

    async def boom(**kw):
        raise RuntimeError("db down")

    original = dao.UnifiedTurnDao.get_latest_summary
    dao.UnifiedTurnDao.get_latest_summary = staticmethod(boom)
    try:
        assert await UnifiedGraph._load_summary(
            thread_id="U", tenant_id=1, user_id=2
        ) is None
    finally:
        dao.UnifiedTurnDao.get_latest_summary = original


@pytest.mark.asyncio
async def test_no_compress_before_trigger_turn():
    """未到触发轮次返回 None（不写摘要，也不调用 LLM）。"""
    got = await UnifiedGraph._maybe_compress_summary(
        turn_index=5,
        history=[HumanMessage(content="q"), AIMessage(content="a")],
        existing_summary="old",
    )
    assert got is None


@pytest.mark.asyncio
async def test_compress_on_trigger_turn(monkeypatch):
    """到达触发轮次时调用 LLM 压缩并返回摘要文本。"""
    import sys
    from types import SimpleNamespace

    captured: dict = {}

    from langchain_core.runnables import RunnableLambda

    def capture(prompt_value):
        captured["text"] = str(prompt_value)
        return "压缩后的摘要"

    async def fake_get_llm(*a, **k):
        return RunnableLambda(capture)

    fake_factory = SimpleNamespace(get_llm=fake_get_llm)
    monkeypatch.setitem(sys.modules, "backend.common.llm.llm_factory", fake_factory)

    got = await UnifiedGraph._maybe_compress_summary(
        turn_index=6,
        history=[HumanMessage(content="q"), AIMessage(content="a")],
        existing_summary="old",
    )
    assert got == "压缩后的摘要"
    assert "old" in captured["text"]
    assert "用户: q" in captured["text"]


@pytest.mark.asyncio
async def test_compress_failure_keeps_none(monkeypatch):
    """LLM 压缩抛错返回 None（调用方不写新摘要，旧摘要自然保留）。"""
    import sys
    from types import SimpleNamespace

    fake_factory = SimpleNamespace(
        get_llm=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("llm down"))
    )
    monkeypatch.setitem(sys.modules, "backend.common.llm.llm_factory", fake_factory)

    got = await UnifiedGraph._maybe_compress_summary(
        turn_index=6,
        history=[HumanMessage(content="q"), AIMessage(content="a")],
        existing_summary="old",
    )
    assert got is None
