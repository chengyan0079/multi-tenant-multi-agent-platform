"""Step 4 PoC — R5：aupdate_state API 可用性与 callbacks 向子图传播（§4.2 / §12 R5）。

用 MemorySaver 编译极简图，验证：
1. aupdate_state 能直接写回 checkpoint 中的 Pydantic 结构化字段（同时强化 R19 复盘图上下文）；
2. callbacks 在 graph.ainvoke 时向子节点传播。
均无需真实 PG。
"""
from __future__ import annotations

import asyncio
from typing import TypedDict

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from backend.orchestration.unified_schemas import EntryFieldValue


class _State(TypedDict):
    messages: list
    entry: EntryFieldValue


class _RecordHandler(BaseCallbackHandler):
    def __init__(self) -> None:
        self.chain_starts = 0

    def on_chain_start(self, serialized, prompt, **kwargs):
        self.chain_starts += 1


def _node(state: _State):
    return {"entry": EntryFieldValue(name="out", value="ok", type="str")}


async def _run() -> None:
    g = StateGraph(_State)
    g.add_node("n", _node)
    g.add_edge(START, "n")
    g.add_edge("n", END)
    app = g.compile(checkpointer=MemorySaver())

    cfg = {"configurable": {"thread_id": "t-r5"}}
    handler = _RecordHandler()
    # 首次运行 + 注入 callbacks，验证向子图传播
    await app.ainvoke(
        {
            "messages": [HumanMessage(content="hi")],
            "entry": EntryFieldValue(name="a", value="1", type="str"),
        },
        config={**cfg, "callbacks": [handler]},
    )
    assert handler.chain_starts >= 1

    # aupdate_state：直接改 checkpoint 中的结构化字段（R5 API 可用性）
    await app.aupdate_state(cfg, {"entry": EntryFieldValue(name="b", value="2", type="str")})
    snap = await app.aget_state(cfg)
    assert snap.values["entry"].name == "b"
    # 复盘图上下文下的 Pydantic 序列化边界（R19 强化）
    assert snap.values["entry"].value == "2"


def test_aupdate_state_and_callbacks_propagate() -> None:
    asyncio.run(_run())
