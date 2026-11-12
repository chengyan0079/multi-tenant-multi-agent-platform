"""Step 6 编排核心 DB-free 单测：路由 / 鉴权 / 入口校验 / dispatch / pipeline / 写回。

全部依赖注入（registry / orchestrator / thread_dao / conversation_service / classify_fn / authz / plan_fn），
不触真实 DB / Redis / LLM / LangGraph 图执行。
"""
from __future__ import annotations

import pytest

from backend.orchestration.agent_registry import AgentRegistry
from backend.orchestration.agent_spec import AgentSpec
from backend.orchestration.unified_dispatch import DefaultAgentAdapter, dispatch
from backend.orchestration.unified_graph import UnifiedGraph
from backend.orchestration.unified_intent import UnifiedRouter
from backend.orchestration.unified_schemas import (
    EntryField,
    EntryFieldType,
    EntryFieldValue,
    EntryPayload,
    InitValuesPayload,
    IntentResponse,
    PipelinePlan,
    PipelineStep,
)
from backend.prompts import unified as prompts


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #
class FakeOrchestrator:
    def __init__(self, registry: AgentRegistry) -> None:
        self._registry = registry
        self.calls: list[tuple] = []

    async def run_agent(self, agent_type: str, thread_id: str, inputs: dict) -> dict:
        self.calls.append((agent_type, thread_id, inputs))
        return {"content": f"answer from {agent_type}"}


class FakeThreadDao:
    def __init__(self) -> None:
        self._n = 0

    async def get_or_create(self, *, session_key: str, tenant_id: int, user_id: int) -> dict:
        self._n += 1
        return {"id": f"U{self._n}", "session_key": session_key}

    async def next_turn_index(self, thread_id: str) -> int:
        return 1


class FakeConv:
    def __init__(self) -> None:
        self.turns: list[dict] = []

    async def append_turn(self, **kw) -> str:
        self.turns.append(kw)
        return "local"


def _build_registry() -> AgentRegistry:
    reg = AgentRegistry()
    reg.register(
        "qa",
        lambda: None,
        spec=AgentSpec(
            agent_type="qa",
            display_name="智能问答",
            description="问答",
            intent_labels=("qa",),
            intent_examples=("怎么复习",),
            default_agent=True,
            execution_mode="stream",
        ),
    )
    reg.register(
        "interview",
        lambda: None,
        spec=AgentSpec(
            agent_type="interview",
            display_name="模拟面试",
            description="面试",
            intent_labels=("interview",),
            scope="interview:ask",
            execution_mode="stream",
            init_prompt="请填写目标岗位",
            guidance_action_label="填写岗位",
            entry_fields=(
                EntryField(name="target_position", label="岗位", type=EntryFieldType.STR, required=True),
            ),
        ),
    )
    reg.register(
        "exam",
        lambda: None,
        spec=AgentSpec(
            agent_type="exam",
            display_name="考试批改",
            description="考试",
            intent_labels=("exam",),
            execution_mode="task",
        ),
    )
    reg.register(
        "multi_agent",
        lambda: None,
        spec=AgentSpec(
            agent_type="multi_agent",
            display_name="组合任务",
            description="串联",
            intent_labels=("multi_agent",),
            execution_mode="pipeline",
        ),
    )
    reg._rebuild_derived()
    return reg


async def _classify(label: str, confidence: float = 0.9):
    async def _fn(system_prompt: str, user_input: str) -> IntentResponse:
        return IntentResponse(label=label, confidence=confidence)

    return _fn


# --------------------------------------------------------------------------- #
# 路由
# --------------------------------------------------------------------------- #
async def test_explicit_routing_skips_classify():
    reg = _build_registry()
    calls: list = []
    orig = await _classify("qa")

    async def counting_fn(s, u):
        calls.append(1)
        return await orig(s, u)

    router = UnifiedRouter(reg)
    d = await router.route(message="随便", explicit_agent_type="qa", classify_fn=counting_fn)
    assert d.source == "explicit"
    assert d.agent_type == "qa"
    assert d.execution_mode == "stream"
    assert calls == []  # 显式通道不触发分类


async def test_rule_greeting_short_circuits():
    reg = _build_registry()
    router = UnifiedRouter(reg)
    d = await router.route(message="你好呀", classify_fn=await _classify("qa"))
    assert d.execution_mode == "rule"
    assert d.agent_type == ""
    reply = router.rule_reply(d.label)
    assert reply == prompts.RULE_REPLY_GREETING


async def test_rule_capability_lists_agents():
    reg = _build_registry()
    router = UnifiedRouter(reg)
    d = await router.route(message="你能做什么", classify_fn=await _classify("qa"))
    assert d.execution_mode == "rule"
    reply = router.rule_reply(d.label, specs=reg.specs())
    assert "智能问答" in reply and "模拟面试" in reply


async def test_implicit_llm_classify_maps_label():
    reg = _build_registry()
    router = UnifiedRouter(reg)
    d = await router.route(message="我想面试", classify_fn=await _classify("interview"))
    assert d.source == "llm"
    assert d.agent_type == "interview"
    assert d.confidence == 0.9


async def test_unknown_label_falls_back_to_default():
    reg = _build_registry()
    router = UnifiedRouter(reg)
    d = await router.route(message="x", classify_fn=await _classify("nope"))
    assert d.source == "fallback"
    assert d.fallback_used is True
    assert d.agent_type == "qa"  # default_agent


# --------------------------------------------------------------------------- #
# 编排引擎
# --------------------------------------------------------------------------- #
async def _make_graph(reg, *, authz=None, plan_fn=None, classify_fn=None):
    orch = FakeOrchestrator(reg)
    graph = UnifiedGraph(
        registry=reg,
        conversation_service=FakeConv(),
        orchestrator=orch,
        thread_dao=FakeThreadDao(),
        authz=authz,
        plan_fn=plan_fn,
        classify_fn=classify_fn,
    )
    return graph, orch


async def test_explicit_stream_dispatches_and_writes_turn():
    reg = _build_registry()
    graph, orch = await _make_graph(reg)
    res = await graph.run(
        session_id="S1", tenant_id=1, user_id=2, message="怎么复习", agent_type="qa"
    )
    assert res.routing.source == "explicit"
    assert res.status == "success"
    assert orch.calls and orch.calls[0][0] == "qa"
    assert res.outcome.content == "answer from qa"
    assert len(graph._conv.turns) == 1
    turn = graph._conv.turns[0]
    assert turn["assistant_content"] == "answer from qa"
    assert turn["agent_type"] == "qa"
    assert turn["status"] == "success"


async def test_rule_reply_no_dispatch():
    reg = _build_registry()
    graph, orch = await _make_graph(reg, classify_fn=await _classify("qa"))
    res = await graph.run(session_id="S2", tenant_id=1, user_id=2, message="你好")
    assert res.routing.execution_mode == "rule"
    assert orch.calls == []  # 规则回复不调子图
    assert res.outcome is None
    assert graph._conv.turns[0]["assistant_content"] == prompts.RULE_REPLY_GREETING


async def test_required_entry_missing_blocks_dispatch():
    reg = _build_registry()
    graph, orch = await _make_graph(reg, classify_fn=await _classify("interview"))
    res = await graph.run(session_id="S3", tenant_id=1, user_id=2, message="我想面试")
    assert res.status == "failed"
    assert res.error_code == "INIT_REQUIRED"
    assert orch.calls == []  # 入口字段缺失不启动图
    assert any(e.event_type == "guidance" for e in res.events)


async def test_required_entry_provided_dispatches():
    reg = _build_registry()
    graph, orch = await _make_graph(reg, classify_fn=await _classify("interview"))
    entry = EntryPayload(
        fields=[EntryFieldValue(name="target_position", value="后端工程师")]
    )
    res = await graph.run(
        session_id="S4", tenant_id=1, user_id=2, message="面试", agent_type="interview", entry=entry
    )
    assert res.status == "success"
    assert orch.calls and orch.calls[0][0] == "interview"


async def test_forbidden_agent_blocks():
    reg = _build_registry()
    graph, orch = await _make_graph(
        reg, authz=lambda at, tid, uid: at != "qa", classify_fn=await _classify("qa")
    )
    res = await graph.run(
        session_id="S5", tenant_id=1, user_id=2, message="怎么复习", agent_type="qa"
    )
    assert res.status == "failed"
    assert res.error_code == "FORBIDDEN"
    assert orch.calls == []
    assert any(e.event_type == "error" for e in res.events)


# --------------------------------------------------------------------------- #
# Pipeline
# --------------------------------------------------------------------------- #
async def _plan_fn(message: str, specs) -> PipelinePlan:
    return PipelinePlan(
        title="组合",
        steps=[
            PipelineStep(step="1", agent_type="qa", label="问答"),
            PipelineStep(step="2", agent_type="interview", label="面试"),
        ],
    )


async def test_pipeline_runs_all_steps():
    reg = _build_registry()
    graph, orch = await _make_graph(
        reg, plan_fn=_plan_fn, classify_fn=await _classify("multi_agent")
    )
    res = await graph.run(session_id="S6", tenant_id=1, user_id=2, message="帮我做组合任务")
    assert res.routing.execution_mode == "pipeline"
    agents = [c[0] for c in orch.calls]
    assert agents == ["qa", "interview"]
    assert sum(1 for e in res.events if e.event_type == "pipeline_step_result") == 2
    assert any(e.event_type == "pipeline_result" for e in res.events)
    # 每步 + 整体共 3 条 turn
    assert len(graph._conv.turns) == 3


async def test_pipeline_step_forbidden_blocks_entire():
    reg = _build_registry()
    graph, orch = await _make_graph(
        reg,
        plan_fn=_plan_fn,
        classify_fn=await _classify("multi_agent"),
        authz=lambda at, tid, uid: at != "interview",
    )
    res = await graph.run(session_id="S7", tenant_id=1, user_id=2, message="组合")
    assert res.status == "failed"
    assert res.error_code == "FORBIDDEN"
    # 第一步 qa 已执行，第二步 interview 被拦 → 不全跑
    assert [c[0] for c in orch.calls] == ["qa"]
    assert any(e.event_type == "error" for e in res.events)


# --------------------------------------------------------------------------- #
# 保留 label（追问 / 组合任务）/ init_values 透传
# --------------------------------------------------------------------------- #
async def test_reserved_label_clarify_maps_to_clarify_mode():
    reg = _build_registry()
    router = UnifiedRouter(reg)
    d = await router.route(message="我还缺什么", classify_fn=await _classify("clarify"))
    assert d.source == "llm"
    assert d.label == "clarify"
    assert d.agent_type == "clarify"
    assert d.execution_mode == "clarify"


async def test_reserved_label_multi_agent_maps_to_pipeline():
    reg = _build_registry()
    router = UnifiedRouter(reg)
    d = await router.route(message="组合任务", classify_fn=await _classify("multi_agent"))
    assert d.agent_type == "multi_agent"
    assert d.execution_mode == "pipeline"


async def test_classify_init_values_passthrough():
    reg = _build_registry()
    router = UnifiedRouter(reg)

    async def _fn(s, u):
        return IntentResponse(
            label="interview", confidence=0.8,
            init_values=InitValuesPayload(target_position="后端"),
        )

    d = await router.route(message="面试", classify_fn=_fn)
    assert d.agent_type == "interview"
    assert d.init_values.target_position == "后端"


# --------------------------------------------------------------------------- #
# 追问：规则回复全类（greeting/thanks/bye/identity/capability 已部分覆盖）
# --------------------------------------------------------------------------- #
async def test_rule_thanks_bye_identity_replies():
    reg = _build_registry()
    router = UnifiedRouter(reg)
    fn = await _classify("qa")
    for msg, rule, expected in [
        ("谢谢啦", "thanks", prompts.RULE_REPLY_THANKS),
        ("再见", "bye", prompts.RULE_REPLY_BYE),
        ("你是谁", "identity", prompts.RULE_REPLY_IDENTITY),
    ]:
        d = await router.route(message=msg, classify_fn=fn)
        assert d.execution_mode == "rule"
        assert d.label == rule
        assert router.rule_reply(d.label) == expected


# --------------------------------------------------------------------------- #
# 分类异常：回落默认 Agent，不中断
# --------------------------------------------------------------------------- #
async def test_classify_exception_falls_back_to_default():
    reg = _build_registry()
    router = UnifiedRouter(reg)

    async def _boom(s, u):
        raise RuntimeError("llm down")

    d = await router.route(message="任意", classify_fn=_boom)
    assert d.source == "fallback"
    assert d.fallback_used is True
    assert d.agent_type == "qa"  # default_agent


# --------------------------------------------------------------------------- #
# dispatch：未知执行模式直接抛 ValueError（早于任何子图调用）
# --------------------------------------------------------------------------- #
async def test_dispatch_unknown_mode_raises_value_error():
    reg = _build_registry()
    spec = AgentSpec(agent_type="bogus", display_name="x", execution_mode="bogus")
    with pytest.raises(ValueError):
        await dispatch(
            agent_type="bogus",
            unified_state={"thread_id": "U", "messages": []},
            parent_cfg={},
            entry=None,
            attachments=[],
            spec=spec,
            adapter=None,
            orchestrator=None,
            registry=reg,
            trace_id="t",
            turn_id="u",
            tenant_id=1,
            user_id=2,
        )


# --------------------------------------------------------------------------- #
# 跨 Agent 切换：同会话连续两轮指定不同 agent_type，第二轮派发到新 Agent
# --------------------------------------------------------------------------- #
async def test_cross_agent_switch_dispatches_new_agent():
    reg = _build_registry()
    graph, orch = await _make_graph(reg, authz=lambda at, tid, uid: True)
    await graph.run(session_id="SX", tenant_id=1, user_id=2, message="怎么复习", agent_type="qa")
    await graph.run(
        session_id="SX", tenant_id=1, user_id=2, message="面试", agent_type="interview",
        entry=EntryPayload(fields=[EntryFieldValue(name="target_position", value="后端")]),
    )
    assert [c[0] for c in orch.calls] == ["qa", "interview"]


# --------------------------------------------------------------------------- #
# 真实停用：注册表 set_enabled(False) 经 _authorize 拦截（非仅 authz lambda）
# --------------------------------------------------------------------------- #
async def test_disabled_agent_blocks_via_registry():
    # 显式请求已停用 Agent → route 直接返回 FORBIDDEN，不再静默兜底重路由
    reg = _build_registry()
    reg.set_enabled("exam", False)  # exam 无 scope，避开 has_scope 上下文依赖
    graph, orch = await _make_graph(reg)
    res = await graph.run(
        session_id="SD", tenant_id=1, user_id=2, message="出卷", agent_type="exam"
    )
    assert res.status == "failed"
    assert res.error_code == "FORBIDDEN"
    assert orch.calls == []  # 未开通不启动子图


async def test_explicit_unknown_agent_falls_back_not_forbidden():
    # 完全未知的类型仍走默认兜底，不应被误判为 FORBIDDEN
    reg = _build_registry()
    graph, orch = await _make_graph(reg, classify_fn=await _classify("qa"))
    res = await graph.run(
        session_id="SU", tenant_id=1, user_id=2, message="随便", agent_type="ghost_agent"
    )
    assert res.status == "success"
    assert res.error_code is None
    assert [c[0] for c in orch.calls] == ["qa"]  # 兜底到默认 Agent
