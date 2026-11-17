"""DSL 串行编排测试：分区带 turn_id、步进记录、拒绝停步、非法 Agent 拦截。"""
from __future__ import annotations

import pytest

from backend.orchestration.agent_registry import AgentRegistry
from backend.orchestration.agent_spec import AgentSpec
from backend.orchestration.orchestrator import Orchestrator
from backend.observability.exception import TenantError


def _registry() -> AgentRegistry:
    reg = AgentRegistry()
    for name in ("qa", "db_review", "db_release"):
        reg.register(
            name,
            lambda: None,
            spec=AgentSpec(agent_type=name, display_name=name, intent_labels=(name,)),
        )
    reg._rebuild_derived()
    return reg


class _FakeGraph:
    def __init__(self, outcomes: list[dict]) -> None:
        self._outcomes = list(outcomes)

    async def ainvoke(self, inputs: dict, config: dict) -> dict:
        out = dict(inputs)
        out.update(self._outcomes.pop(0) if self._outcomes else {})
        return out


@pytest.mark.asyncio
async def test_run_plan_uses_turn_partition_and_records_steps(monkeypatch):
    """每步分区带 turn_id，且 carry 记录每步输出。"""
    reg = _registry()
    orch = Orchestrator(reg)
    meta = reg.get("qa")
    fake_graph = _FakeGraph([{"content": "A"}, {"content": "B"}])
    meta.build_graph = lambda: fake_graph
    seen_partitions: list[str] = []
    original = orch.run_agent

    async def spy(agent_type, thread_id, inputs):
        seen_partitions.append(thread_id)
        return await original(agent_type, thread_id, inputs)

    orch.run_agent = spy
    plan = {
        "type": "sequence",
        "steps": [{"type": "agent", "agent": "qa"}, {"type": "agent", "agent": "qa"}],
    }
    result = await orch.run_plan(
        plan, "U", {"tenant_id": 1, "user_id": 2, "turn_id": "T1"}
    )

    assert seen_partitions == ["U:qa:T1", "U:qa:T1"]
    assert [s["content"] for s in result["_step_results"]] == ["A", "B"]
    assert result["_current_step"] == 2


@pytest.mark.asyncio
async def test_run_plan_stops_on_rejection():
    """某步返回 rejected 后不再执行后续步骤。"""
    reg = _registry()
    orch = Orchestrator(reg)

    async def fake_run_agent(agent_type, thread_id, inputs):
        if agent_type == "db_review":
            return {"status": "rejected", "content": "拒绝"}
        return {"content": "不应执行"}

    orch.run_agent = fake_run_agent
    plan = {
        "type": "sequence",
        "steps": [
            {"type": "agent", "agent": "db_review"},
            {"type": "agent", "agent": "db_release"},
        ],
    }
    result = await orch.run_plan(plan, "U", {"turn_id": "T2"})

    assert len(result["_step_results"]) == 1
    assert result["status"] == "rejected"


@pytest.mark.asyncio
async def test_run_plan_rejects_unregistered_agent():
    """LLM 编造的 Agent 名被注册表拦截。"""
    reg = _registry()
    orch = Orchestrator(reg)
    plan = {"type": "sequence", "steps": [{"type": "agent", "agent": "not_exist"}]}

    with pytest.raises(TenantError):
        await orch.run_plan(plan, "U", {"turn_id": "T3"})
