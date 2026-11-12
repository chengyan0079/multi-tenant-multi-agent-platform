"""Step 3 注册表与 spec 单测（§3 / §16 验收 V1–V14 可达项）。

覆盖：4 个真实 metadata() 返回 AgentSpec 且通过 validate_specs；specs() 按开关过滤；
DB 覆写 merge；动态入口校验模型经注册表构建；render_route_prompt 仅含启用 spec。
"""
from __future__ import annotations

from backend.agents.exam.agent import ExamAgent
from backend.agents.interview.agent import InterviewAgent
from backend.agents.qa.agent import QAAgent
from backend.agents.resume.agent import ResumeAgent
from backend.orchestration.agent_registry import AgentRegistry
from backend.orchestration.agent_spec import AgentSpec, merge_db_overrides


def _registry_with_real_agents() -> AgentRegistry:
    reg = AgentRegistry()
    for cls in (QAAgent, InterviewAgent, ExamAgent, ResumeAgent):
        cls().register_into(reg)
    return reg


def test_real_agents_metadata_are_specs_and_validate() -> None:
    reg = _registry_with_real_agents()
    reg.validate_specs()  # 不应抛异常
    specs = reg.specs()
    assert len(specs) == 4
    # V2：恰有一个 default_agent
    assert sum(1 for s in specs if s.default_agent) == 1
    # 4 个 scope 均来自 VALID_SCOPES（QA_ASK/INTERVIEW_ASK/EXAM_UPLOAD/RESUME_UPLOAD）
    scopes = {s.scope for s in specs}
    assert {"qa:ask", "interview:ask", "exam:upload", "resume:upload"} == scopes


def test_specs_filter_disabled() -> None:
    reg = _registry_with_real_agents()
    reg.set_enabled("exam", False)
    types = {s.agent_type for s in reg.specs()}
    assert "exam" not in types
    assert "qa" in types


def test_db_override_merge() -> None:
    spec = AgentSpec(agent_type="x", display_name="orig", description="d", version="1.0.0")
    merged = merge_db_overrides(spec, name="DB名", description=None, version="2.0.0")
    assert merged.display_name == "DB名"
    assert merged.description == "d"
    assert merged.version == "2.0.0"


def test_dynamic_entry_model_via_registry() -> None:
    reg = _registry_with_real_agents()
    reg._rebuild_derived()
    model = reg.get_entry_model("interview")
    assert model is not None
    inst = model(target_position="后端")
    assert inst.target_position == "后端"


def test_render_route_prompt_uses_enabled_only() -> None:
    reg = _registry_with_real_agents()
    prompt = reg.render_route_prompt()
    # 用 display_name 作章节标记（模板常量里的 "exam_id" 不是 exam 章节）
    assert "智能问答" in prompt and "模拟面试" in prompt
    reg.set_enabled("exam", False)
    assert "智能出题" not in reg.render_route_prompt()


def test_label_to_agent_and_scope_maps() -> None:
    reg = _registry_with_real_agents()
    reg._rebuild_derived()
    assert reg.label_to_agent("面试") == "interview"
    assert reg.scope_for_agent("qa") == "qa:ask"
