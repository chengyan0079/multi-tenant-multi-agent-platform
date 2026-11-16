"""Step 3 注册表与 spec 单测（qa 单 Agent 版）。"""
from __future__ import annotations

from backend.agents.qa.agent import QAAgent
from backend.orchestration.agent_registry import AgentRegistry
from backend.orchestration.agent_spec import AgentSpec, merge_db_overrides


def _registry_with_real_agents() -> AgentRegistry:
    reg = AgentRegistry()
    QAAgent().register_into(reg)
    return reg


def test_real_agents_metadata_are_specs_and_validate() -> None:
    reg = _registry_with_real_agents()
    reg.validate_specs()
    specs = reg.specs()
    assert len(specs) == 1
    assert sum(1 for s in specs if s.default_agent) == 1
    scopes = {s.scope for s in specs}
    assert {"unified:ask"} == scopes


def test_specs_filter_disabled() -> None:
    reg = _registry_with_real_agents()
    reg.set_enabled("qa", False)
    types = {s.agent_type for s in reg.specs()}
    assert "qa" not in types


def test_db_override_merge() -> None:
    spec = AgentSpec(agent_type="x", display_name="orig", description="d", version="1.0.0")
    merged = merge_db_overrides(spec, name="DB名", description=None, version="2.0.0")
    assert merged.display_name == "DB名"
    assert merged.description == "d"
    assert merged.version == "2.0.0"


def test_dynamic_entry_model_via_registry() -> None:
    reg = _registry_with_real_agents()
    reg._rebuild_derived()
    reg.get_entry_model("qa")


def test_render_route_prompt_uses_enabled_only() -> None:
    reg = _registry_with_real_agents()
    prompt = reg.render_route_prompt()
    # 断言 spec 行（只包含已启用 Agent），避免与提示词固定文案里的字样混淆
    assert "- qa（知识问答）" in prompt
    reg.set_enabled("qa", False)
    assert "- qa（知识问答）" not in reg.render_route_prompt()


def test_label_to_agent_and_scope_maps() -> None:
    reg = _registry_with_real_agents()
    reg._rebuild_derived()
    assert reg.scope_for_agent("qa") == "unified:ask"
