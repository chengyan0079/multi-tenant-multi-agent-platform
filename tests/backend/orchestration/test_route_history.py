"""路由历史注入测试：历史文本进入分类器，且不重复查询。"""
from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from backend.orchestration.agent_registry import AgentRegistry
from backend.orchestration.agent_spec import AgentSpec
from backend.orchestration.unified_graph import UnifiedGraph
from backend.orchestration.unified_schemas import IntentResponse


def _registry() -> AgentRegistry:
    reg = AgentRegistry()
    reg.register(
        "qa",
        lambda: None,
        spec=AgentSpec(agent_type="qa", display_name="问答", intent_labels=("qa",)),
    )
    reg._rebuild_derived()
    return reg


@pytest.mark.asyncio
async def test_history_for_route_formats_text():
    """历史消息格式化为「用户/助手」文本，供路由 prompt 消解指代。"""
    graph = UnifiedGraph(
        registry=_registry(), conversation_service=None, orchestrator=None, thread_dao=None
    )
    msgs = [HumanMessage(content="帮我评审这条SQL"), AIMessage(content="风险中等")]

    async def fake_load(*a, **k):
        return list(msgs)

    graph._load_history = fake_load
    raw, text = await graph._history_for_route("U", 1, 2)
    assert raw == msgs
    assert "用户: 帮我评审这条SQL" in text
    assert "助手: 风险中等" in text


class _FakeOrch:
    async def run_agent(self, *a, **k):
        return {"content": "ok"}


class _FakeConv:
    async def append_turn(self, **kw):
        return "local"


class _FakeThreadDao:
    async def get_or_create(self, **kw):
        return {"id": "U1"}

    async def next_turn_index(self, thread_id):
        return 1


@pytest.mark.asyncio
async def test_route_receives_history_text():
    """run() 的分类器拿到的 user_input 含历史文本。"""
    captured: dict = {}

    async def classify(system_prompt: str, user_input: str) -> IntentResponse:
        captured["user_input"] = user_input
        return IntentResponse(label="qa", confidence=0.9)

    graph = UnifiedGraph(
        registry=_registry(),
        conversation_service=_FakeConv(),
        orchestrator=_FakeOrch(),
        thread_dao=_FakeThreadDao(),
        classify_fn=classify,
    )
    async def fake_load(*a, **k):
        return [HumanMessage(content="上一轮问过外键"), AIMessage(content="外键用于关联")]

    graph._load_history = fake_load
    await graph.run(session_id="S1", tenant_id=1, user_id=2, message="继续")

    assert "上一轮问过外键" in captured["user_input"]
    assert "用户当前输入" in captured["user_input"]
