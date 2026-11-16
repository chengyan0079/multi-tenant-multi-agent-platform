"""Step 4 PoC — 运行期配置构造（观测一次挂载基础设施）单测。"""
from __future__ import annotations

from backend.orchestration.agent_spec import AgentSpec
from backend.orchestration.unified_runtime import build_run_config


def test_build_run_config_injects_metadata_and_tags() -> None:
    spec = AgentSpec(agent_type="qa", tags=("qa",), version="1.0.0")
    cfg = build_run_config(thread_id="U1", trace_id="trace-abc", spec=spec)

    assert cfg["configurable"]["thread_id"] == "U1"
    md = cfg["metadata"]
    assert md["trace_id"] == "trace-abc"
    assert md["source"] == "unified"
    assert md["agent_type"] == "qa"
    assert md["spec_version"] == "1.0.0"
    assert "unified" in cfg["tags"]
    assert "qa" in cfg["tags"]


def test_build_run_config_preserves_callbacks_when_tracing_disabled() -> None:
    # 无 Langfuse 密钥时 tracing.with_callbacks 原样返回，callbacks 应保留
    spec = AgentSpec(agent_type="interview", tags=(), version="1.0.0")
    sentinel = object()
    cfg = build_run_config(
        thread_id="U2", trace_id="t2", spec=spec, callbacks=[sentinel]
    )
    assert sentinel in cfg.get("callbacks", [])
