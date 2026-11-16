"""Step 4 PoC — R19：Pydantic BaseModel 进 checkpoint 的序列化验证（§4.1 / §12 R19）。

LangGraph 默认 checkpointer 用 JsonPlusSerializer，可原生序列化 Pydantic BaseModel。
本测试直接验证该序列化边界（与 AsyncPostgresSaver 共用同一 serde），无需真实 PG。
"""
from __future__ import annotations

from langgraph.checkpoint.memory import MemorySaver

from backend.orchestration.unified_schemas import (
    AgentCard,
    AgentOutcome,
    EntryFieldValue,
    ProgressLabel,
    RoutingDecisionEvent,
    ShortTermTurn,
    UnifiedEvent,
)


def _sample_objects():
    yield ShortTermTurn(turn_id="t1", role="user", content="上周的偏好")
    yield EntryFieldValue(name="target_position", value="后端", type="str")
    yield AgentCard(icon="chat", badge="常用", sort_order=1, action_label="开始问答")
    yield ProgressLabel(node="ask_question", text="出题")
    yield RoutingDecisionEvent(agent_type="qa", reason="x", confidence=0.9)
    yield UnifiedEvent(
        event_type="routing_decision",
        payload=RoutingDecisionEvent(agent_type="qa", reason="x", confidence=0.9),
    )
    # 嵌套：含判别联合 payload 的列表，验证复杂结构往返
    yield AgentOutcome(
        content="hi",
        events=[
            UnifiedEvent(
                event_type="routing_decision",
                payload=RoutingDecisionEvent(agent_type="qa", reason="x", confidence=0.9),
            )
        ],
    )


def test_default_checkpointer_uses_jsonplus() -> None:
    # AsyncPostgresSaver / MemorySaver 共用默认 serde；确认即 R19 的序列化边界
    serde = MemorySaver().serde
    assert type(serde).__name__ == "JsonPlusSerializer"


def test_serde_roundtrip_pydantic() -> None:
    serde = MemorySaver().serde
    for obj in _sample_objects():
        payload = serde.dumps_typed(obj)
        restored = serde.loads_typed(payload)
        assert restored == obj
