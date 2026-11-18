"""意图路由回归测试（对应路由评测报告里的 D1 / D3 / D4 / D5 / D6）。

- D1 多 Agent 不再截断为 agents[0]，改为保留标签 multi_agent + 编排 DSL。
- D3 `_default_classify` 的 LLM 工厂导入路径可用（旧路径 backend.llm 不存在）。
- D4 规则无命中时 LLM 兜底真正接入 classify_as_intent，且可开关、失败不阻断。
- D5 分类异常必须留日志（含堆栈），不再静默回退。
- D6 串行顺序取命中集合原始次序，不硬编码 db_review/db_release。

全部 DB-free，不连 LLM。
"""
from __future__ import annotations

import pytest

from backend.orchestration import unified_intent as ui
from backend.orchestration.unified_graph import _plan_agents
from backend.orchestration.unified_intent import UnifiedRouter
from backend.services import intent_router as ir
from tests.test_step6_orchestration import _build_registry, _make_graph


@pytest.fixture()
def rule_only(monkeypatch):
    """关闭 LLM 兜底，只验规则层。"""
    monkeypatch.setenv("INTENT_LLM_FALLBACK", "0")


# --------------------------------------------------------------------------- #
# D1：多 Agent → multi_agent + plan（不截断）
# --------------------------------------------------------------------------- #
async def test_single_agent_label(rule_only):
    resp = await ir.classify_as_intent("sp", "这条 alter 语句有什么风险")
    assert resp.label == "db_review"
    assert resp.plan is None
    assert "rule" in resp.reason


async def test_sequential_plan_orders_review_before_release(rule_only):
    resp = await ir.classify_as_intent("sp", "先看下这条 alter 的风险，没问题就帮我发到沙箱")
    assert resp.label == "multi_agent"
    assert resp.plan is not None
    assert resp.plan["type"] == "sequence"
    assert [s["agent"] for s in resp.plan["steps"]] == ["db_review", "db_release"]
    # 评测事件里的 agents 由同一计划推导，顺序保持一致
    assert _plan_agents(resp.plan) == ["db_review", "db_release"]


async def test_parallel_plan_lists_all_agents(rule_only):
    resp = await ir.classify_as_intent("sp", "按规范评审下这条 alter 语句")
    assert resp.label == "multi_agent"
    plan = resp.plan or {}
    assert plan["type"] == "sequence"  # 外层 sequence 以满足 plan["steps"] 判空
    assert plan["steps"][0]["type"] == "parallel"
    assert set(_plan_agents(plan)) == {"db_review", "qa"}


async def test_unmatched_falls_to_clarify(rule_only):
    resp = await ir.classify_as_intent("sp", "看看这个")
    assert resp.label == "clarify"
    assert resp.plan is None
    assert resp.confidence == 0.0


def test_plan_always_carries_steps():
    for flow in ("sequential", "parallel", "branch"):
        plan = ir.plan_from_decision({"flow": flow, "agents": ["qa", "db_review"]})
        assert plan.get("steps"), flow


# --------------------------------------------------------------------------- #
# D3：LLM 结构化分类的导入路径
# --------------------------------------------------------------------------- #
async def test_default_classify_resolves_llm_factory(monkeypatch):
    import backend.common.llm.llm_factory as fac

    class _LLM:
        async def ainvoke(self, messages):
            return ui.IntentResponse(label="qa", confidence=0.8)

    async def fake_get_structured_llm(agent_type, schema):
        assert agent_type == "unified"
        assert schema is ui.IntentResponse
        return _LLM()

    monkeypatch.setattr(fac, "get_structured_llm", fake_get_structured_llm)
    resp = await ui._default_classify("system", "用户输入")
    assert resp.label == "qa"


# --------------------------------------------------------------------------- #
# D4：规则无命中时的 LLM 兜底（可开关 / 失败不阻断）
# --------------------------------------------------------------------------- #
async def test_llm_fallback_disabled_never_calls_llm(monkeypatch):
    monkeypatch.setenv("INTENT_LLM_FALLBACK", "0")
    calls: list[str] = []

    async def fake(text: str) -> list[str]:
        calls.append(text)
        return ["qa"]

    monkeypatch.setattr(ir, "_llm_agents", fake)
    resp = await ir.classify_as_intent("sp", "看看这个")
    assert resp.label == "clarify"
    assert calls == []


async def test_llm_fallback_used_when_rule_misses(monkeypatch):
    monkeypatch.setenv("INTENT_LLM_FALLBACK", "1")

    async def fake(text: str) -> list[str]:
        return ["db_review"]

    monkeypatch.setattr(ir, "_llm_agents", fake)
    resp = await ir.classify_as_intent("sp", "帮我看看这个")
    assert resp.label == "db_review"
    assert "llm" in resp.reason


async def test_llm_fallback_empty_keeps_clarify(monkeypatch):
    monkeypatch.setenv("INTENT_LLM_FALLBACK", "1")

    async def fake(text: str) -> list[str]:
        return []

    monkeypatch.setattr(ir, "_llm_agents", fake)
    resp = await ir.classify_as_intent("sp", "看看这个")
    assert resp.label == "clarify"


async def test_llm_fallback_skipped_when_rule_hits(monkeypatch):
    monkeypatch.setenv("INTENT_LLM_FALLBACK", "1")

    async def fake(text: str) -> list[str]:
        raise AssertionError("规则已命中，不应调用 LLM")

    monkeypatch.setattr(ir, "_llm_agents", fake)
    resp = await ir.classify_as_intent("sp", "这条 alter 有风险吗")
    assert resp.label == "db_review"


# --------------------------------------------------------------------------- #
# D5：分类异常必须留痕 + 回退默认
# --------------------------------------------------------------------------- #
async def test_classify_exception_logged_and_falls_back(monkeypatch):
    reg = _build_registry()
    logs: list[tuple[str, dict]] = []

    class _Logger:
        def warning(self, msg, **kw):
            logs.append((str(msg), kw))

        def info(self, msg):  # pragma: no cover - 本用例不该走到
            logs.append((str(msg), {}))

    monkeypatch.setattr(ui, "logger", _Logger())

    async def boom(system_prompt: str, user_input: str):
        raise RuntimeError("llm down")

    router = UnifiedRouter(reg)
    d = await router.route(message="随便聊两句", classify_fn=boom)
    assert d.source == "fallback"
    assert d.fallback_used is True
    assert logs and "意图分类异常" in logs[0][0]
    assert logs[0][1].get("exc_info") is True  # 带栈，便于定位


# --------------------------------------------------------------------------- #
# D6：串行顺序不硬编码具体 Agent
# --------------------------------------------------------------------------- #
def test_sequential_order_follows_hit_order(monkeypatch):
    monkeypatch.setattr(ir, "_KEYWORDS", {"qa": ("规范",), "interview": ("面试",)})
    monkeypatch.setattr(ir, "_SEQUENTIAL", [({"qa", "interview"}, "combo")])
    monkeypatch.setattr(ir, "_PARALLEL", [])
    decision = ir.decide_flow(ir._rule_agents("按规范面试"))
    assert decision["flow"] == "sequential"
    assert decision["agents"] == ["qa", "interview"]


# --------------------------------------------------------------------------- #
# 端到端：桥接函数 → 统一编排图 → 真的跑多步
# --------------------------------------------------------------------------- #
async def test_classify_as_intent_drives_pipeline(monkeypatch):
    monkeypatch.setenv("INTENT_LLM_FALLBACK", "0")
    monkeypatch.setattr(ir, "_KEYWORDS", {"qa": ("规范",), "interview": ("面试",)})
    monkeypatch.setattr(ir, "_SEQUENTIAL", [({"qa", "interview"}, "combo")])
    monkeypatch.setattr(ir, "_PARALLEL", [])

    reg = _build_registry()
    graph, orch = await _make_graph(reg, classify_fn=ir.classify_as_intent)
    res = await graph.run(session_id="S9", tenant_id=1, user_id=2, message="按规范面试")

    assert res.routing.label == "multi_agent"
    assert res.routing.execution_mode == "pipeline"
    assert [c[0] for c in orch.calls] == ["qa", "interview"]  # 两步都跑了
    assert sum(1 for e in res.events if e.event_type == "pipeline_step_result") == 2
    assert any(e.event_type == "pipeline_result" for e in res.events)
