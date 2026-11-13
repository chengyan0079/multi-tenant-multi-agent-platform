"""Dispatch 契约：adapter 在框架边界转换 dict 与业务模型；dispatch 按 execution_mode 分流。"""
from __future__ import annotations

from typing import Any, AsyncIterator, Awaitable, Callable, Optional, Protocol

from langchain_core.runnables import RunnableConfig

from backend.orchestration.agent_spec import AgentSpec
from backend.orchestration.unified_runtime import build_run_config
from backend.orchestration.unified_schemas import (
    AgentOutcome,
    ArtifactRef,
    AttachmentRef,
    EntryPayload,
    PipelinePlan,
    PersistencePayload,
    ProgressEvent,
    TaskStartedEvent,
    TokenEvent,
    UnifiedEvent,
)


def fork_config(parent_cfg: RunnableConfig, *, thread_id: str) -> RunnableConfig:
    """保留同一组 callbacks，仅覆盖子图 thread_id 分区键（§4.7 / §4.8）。

    任何子图都不得使用裸 U 作 thread_id，否则与薄图 UnifiedState 同名 key 互相覆盖。
    """
    cfg: RunnableConfig = {
        "configurable": {"thread_id": thread_id},
        "metadata": dict(parent_cfg.get("metadata", {})),
        "tags": list(parent_cfg.get("tags", [])),
    }
    if parent_cfg.get("callbacks"):
        cfg["callbacks"] = list(parent_cfg["callbacks"])
    return cfg


def _partition_for(spec: AgentSpec, *, thread_id: str, turn_id: str, artifact_id: str) -> str:
    """§4.8 分区键：checkpoint_scope=True 按业务实例恒定，否则按轮次。"""
    if spec.checkpoint_scope:
        return f"{thread_id}:{spec.agent_type}:{artifact_id or turn_id}"
    return f"{thread_id}:{spec.agent_type}:{turn_id}"


class AgentAdapter(Protocol):
    """子图适配协议（§3.7）。新增 Agent 最多实现一个 adapter，统一层零改动。"""

    def to_subgraph_input(
        self,
        *,
        unified_state: Any,
        spec: AgentSpec,
        entry: Optional[EntryPayload],
        attachments: list[AttachmentRef],
    ) -> dict:
        ...

    def from_subgraph_output(self, result: dict, spec: AgentSpec) -> AgentOutcome:
        ...

    async def stream(
        self,
        *,
        agent_type: str,
        thread_id: str,
        initial_state: dict,
        config: RunnableConfig,
        spec: AgentSpec,
        meta_sink: Optional[dict] = None,
    ) -> AsyncIterator[UnifiedEvent]:
        ...

    async def on_first_turn(
        self,
        *,
        spec: AgentSpec,
        turn_id: str,
        entry: Optional[EntryPayload],
        attachments: list[AttachmentRef],
        tenant_id: int,
        user_id: int,
        trace_id: str,
        thread_id: str,
    ) -> dict:
        ...

    def normalize_events(self, event: Any, spec: AgentSpec) -> Optional[dict]:
        ...


class DefaultAgentAdapter:
    """通用 adapter：stream 走 orchestrator.run_agent 收集结果；task 由注入回调建业务行。"""

    def __init__(
        self,
        *,
        orchestrator: Any,
        task_starter: Optional[
            Callable[..., Awaitable[dict]]
        ] = None,
    ) -> None:
        self._orchestrator = orchestrator
        self._task_starter = task_starter

    def to_subgraph_input(
        self,
        *,
        unified_state: Any,
        spec: AgentSpec,
        entry: Optional[EntryPayload],
        attachments: list[AttachmentRef],
    ) -> dict:
        # 单向注入：本轮消息窗口 + existing_summary；不反向写回统一层（§4.7）
        return {
            "messages": list(unified_state.get("messages", [])),
            "existing_summary": unified_state.get("existing_summary"),
        }

    def from_subgraph_output(self, result: dict, spec: AgentSpec) -> AgentOutcome:
        content = result.get("content") or result.get("answer") or ""
        return AgentOutcome(content=content, events=[], state_patch=None, persistence=None)

    async def stream(
        self,
        *,
        agent_type: str,
        thread_id: str,
        initial_state: dict,
        config: RunnableConfig,
        spec: AgentSpec,
        meta_sink: Optional[dict] = None,
    ) -> AsyncIterator[UnifiedEvent]:
        """真流式：从 Orchestrator 的 astream_events 过滤映射为统一事件。

        仅对 spec.generate_nodes 上的 on_chat_model_stream 透出 token，对
        spec.progress_labels 上的 on_chain_start 透出进度；其余事件丢弃。
        命中生成节点结束时的结构化输出（answer_mode/confidence/sources）写入 meta_sink，
        供编排层追加 meta 帧。
        """
        generate_nodes = set(spec.generate_nodes)
        progress_labels = {p.node: p.text for p in spec.progress_labels}

        streamer = getattr(self._orchestrator, "run_agent_stream", None)
        # 编排器不支持流式（如测试替身）时回落到同步收集，仍能产出 token 帧
        if streamer is None:
            result = await self._orchestrator.run_agent(agent_type, thread_id, initial_state)
            content = result.get("content") or result.get("answer") or ""
            if content:
                yield UnifiedEvent(event_type="token", payload=TokenEvent(content=content))
            return

        async for raw in streamer(agent_type, thread_id, initial_state, config):
            evt = raw.get("event")
            node = (raw.get("metadata") or {}).get("langgraph_node", "")
            if evt == "on_chain_start" and node in progress_labels:
                yield UnifiedEvent(
                    event_type="progress", payload=ProgressEvent(stage=progress_labels[node])
                )
            elif evt == "on_chat_model_stream" and node in generate_nodes:
                chunk = (raw.get("data") or {}).get("chunk")
                if chunk and getattr(chunk, "content", None):
                    yield UnifiedEvent(
                        event_type="token", payload=TokenEvent(content=chunk.content)
                    )
            elif evt == "on_chain_end" and node in generate_nodes and meta_sink is not None:
                output = (raw.get("data") or {}).get("output") or {}
                if isinstance(output, dict):
                    if output.get("answer_mode"):
                        meta_sink["answer_mode"] = output["answer_mode"]
                    if output.get("sources") is not None:
                        meta_sink["sources"] = output["sources"]
                    conf = (output.get("structured_output") or {}).get("confidence")
                    if conf is not None:
                        meta_sink["confidence"] = conf

    async def on_first_turn(
        self,
        *,
        spec: AgentSpec,
        turn_id: str,
        entry: Optional[EntryPayload],
        attachments: list[AttachmentRef],
        tenant_id: int,
        user_id: int,
        trace_id: str,
        thread_id: str,
    ) -> dict:
        if self._task_starter is None:
            return {
                "artifact_type": spec.agent_type,
                "artifact_id": turn_id,
                "task_id": "",
            }
        return await self._task_starter(
            spec=spec,
            turn_id=turn_id,
            entry=entry,
            attachments=attachments,
            tenant_id=tenant_id,
            user_id=user_id,
            trace_id=trace_id,
            thread_id=thread_id,
        )

    def normalize_events(self, event: Any, spec: AgentSpec) -> Optional[dict]:
        return event


async def dispatch(
    *,
    agent_type: str,
    unified_state: Any,
    parent_cfg: RunnableConfig,
    entry: Optional[EntryPayload],
    attachments: list[AttachmentRef],
    spec: AgentSpec,
    adapter: Any,
    orchestrator: Any,
    registry: Any,
    trace_id: str,
    turn_id: str,
    tenant_id: int,
    user_id: int,
) -> AgentOutcome:
    """按 execution_mode 分发到子图，返回 AgentOutcome（§4.7）。编排层无 if agent_type==...。"""
    partition = _partition_for(
        spec, thread_id=unified_state.get("thread_id", ""), turn_id=turn_id, artifact_id=""
    )
    cfg = fork_config(parent_cfg, thread_id=partition)

    if spec.execution_mode == "stream":
        initial = adapter.to_subgraph_input(
            unified_state=unified_state, spec=spec, entry=entry, attachments=attachments
        )
        # 复用既有 Orchestrator.run_agent（内部 build_graph + tracing）
        result = await orchestrator.run_agent(agent_type, partition, initial)
        return adapter.from_subgraph_output(result, spec)

    if spec.execution_mode == "task":
        first = await adapter.on_first_turn(
            spec=spec,
            turn_id=turn_id,
            entry=entry,
            attachments=attachments,
            tenant_id=tenant_id,
            user_id=user_id,
            trace_id=trace_id,
            thread_id=unified_state.get("thread_id", ""),
        )
        return AgentOutcome(
            content=first.get("summary", ""),
            events=[
                UnifiedEvent(
                    event_type="task_started",
                    payload=TaskStartedEvent(
                        artifact_type=first.get("artifact_type", ""),
                        artifact_id=first.get("artifact_id", ""),
                        task_id=first.get("task_id", ""),
                    ),
                )
            ],
            persistence=PersistencePayload(
                artifact=ArtifactRef(
                    artifact_type=first.get("artifact_type", ""),
                    artifact_id=first.get("artifact_id", ""),
                )
            ),
        )

    if spec.execution_mode == "clarify":
        return AgentOutcome(content="", events=[], state_patch=None, persistence=None)

    if spec.execution_mode == "pipeline":
        from backend.orchestration.pipeline_runner import PipelineRunner

        runner = PipelineRunner(orchestrator=orchestrator, adapter=adapter, registry=registry)
        # pipeline 计划由编排层（plan_fn）生成后传入；此处仅兜底为空计划
        plan = PipelinePlan()
        return await runner.run(
            plan=plan,
            cfg_U=parent_cfg,
            thread_id=unified_state.get("thread_id", ""),
            tenant_id=tenant_id,
            user_id=user_id,
            trace_id=trace_id,
            turn_id=turn_id,
        )

    raise ValueError(f"未知 execution_mode: {spec.execution_mode}")
