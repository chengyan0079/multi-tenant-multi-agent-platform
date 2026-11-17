"""Dispatch 契约：adapter 在框架边界转换 dict 与业务模型；dispatch 按 execution_mode 分流。"""
from __future__ import annotations

from typing import Any, AsyncIterator, Awaitable, Callable, Optional, Protocol

from langchain_core.runnables import RunnableConfig

from backend.agents import AGENT_BUILDERS
from backend.agents.template import AgentTemplate
from backend.orchestration.agent_spec import AgentSpec
from backend.orchestration.unified_runtime import build_run_config
from backend.orchestration.unified_schemas import (
    AgentOutcome,
    ArtifactRef,
    AttachmentRef,
    EntryPayload,
    PersistencePayload,
    ProgressEvent,
    ReasoningEvent,
    TaskStartedEvent,
    TokenEvent,
    UnifiedEvent,
)


def _extract_usage(output: Any) -> dict:
    """从 LLMResult 提取 token 用量（OpenAI usage / LangChain usage_metadata）。"""
    try:
        llm_output = getattr(output, "llm_output", None) or {}
        usage = llm_output.get("token_usage") or llm_output.get("usage") or {}
        if not usage:
            for gens in getattr(output, "generations", None) or []:
                for generation in gens:
                    message = getattr(generation, "message", None)
                    metadata = getattr(message, "usage_metadata", None) or {}
                    if metadata:
                        usage = metadata
                        break
                if usage:
                    break
        if not isinstance(usage, dict):
            return {}
        prompt = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
        completion = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
        total = int(usage.get("total_tokens") or (prompt + completion))
        return {"prompt": prompt, "completion": completion, "total": total}
    except Exception:  # noqa: BLE001 - 统计失败忽略
        return {}


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


def _template_of(agent_type: str):
    """取该 agent_type 的模板实例（非模板/未注册返回 None）。"""
    cls = AGENT_BUILDERS.get(agent_type)
    if cls is None:
        return None
    try:
        inst = cls()
        return inst if isinstance(inst, AgentTemplate) else None
    except Exception:  # noqa: BLE001
        return None


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
        messages = list(unified_state.get("messages", []))
        tpl = _template_of(spec.agent_type)
        if tpl is not None:
            messages = tpl.compress_context({"messages": messages})
        return {
            "messages": messages,
            "existing_summary": unified_state.get("existing_summary"),
            # 关键上下文必须透传：缺 tenant_id 会让检索按租户 0 过滤 → 召回恒为空；
            # 缺 user_id 会让短期/长期记忆、审计写入失败。
            # 不做 `or 0` 兜底：缺失即 fail-fast，避免静默查错租户。
            "tenant_id": int(unified_state["tenant_id"]),
            "user_id": int(unified_state["user_id"]),
            "session_id": unified_state.get("session_id"),
            "thread_id": unified_state.get("thread_id"),
            "turn_id": unified_state.get("turn_id"),
            "trace_id": unified_state.get("trace_id"),
            "thinking": bool(unified_state.get("thinking")),
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
                if chunk is not None:
                    # 思考模式：DeepSeek/OpenAI 兼容网关把推理过程放在 additional_kwargs
                    extra = getattr(chunk, "additional_kwargs", None) or {}
                    meta_extra = getattr(chunk, "response_metadata", None) or {}
                    reasoning = (
                        extra.get("reasoning_content")
                        or extra.get("reasoning")
                        or meta_extra.get("reasoning_content")
                    )
                    if reasoning:
                        yield UnifiedEvent(
                            event_type="reasoning",
                            payload=ReasoningEvent(content=str(reasoning)),
                        )
                    if getattr(chunk, "content", None):
                        yield UnifiedEvent(
                            event_type="token", payload=TokenEvent(content=chunk.content)
                        )
            elif evt == "on_chain_end" and node == "retrieve" and meta_sink is not None:
                # 检索结果快照 → 供「问答结果」展示与 RAGAS context 指标
                # 注意：必须带 score（精排分数）/doc_id，否则前端只能显示 0 分
                output = (raw.get("data") or {}).get("output") or {}
                chunks = output.get("ranked_chunks") if isinstance(output, dict) else None
                if chunks:

                    def _f(chunk: Any, name: str) -> Any:
                        val = getattr(chunk, name, None)
                        if val is None and isinstance(chunk, dict):
                            val = chunk.get(name)
                        return val

                    brief = []
                    for c in chunks[:20]:
                        content = _f(c, "content")
                        if not content:
                            continue
                        score = _f(c, "score")
                        brief.append(
                            {
                                "doc_id": _f(c, "doc_id") or _f(c, "chunk_id"),
                                "chunk_id": _f(c, "chunk_id"),
                                "content": str(content)[:2000],
                                "page": _f(c, "page"),
                                "score": (
                                    round(float(score), 4) if score is not None else None
                                ),
                                "source": _f(c, "source"),
                            }
                        )
                    if brief:
                        meta_sink["contexts"] = brief
            elif evt == "on_chat_model_end" and meta_sink is not None:
                # 累计 token 用量（prompt/completion/total），供前端展示与落库
                usage = _extract_usage((raw.get("data") or {}).get("output"))
                if usage:
                    acc = meta_sink.setdefault("token_usage", {})
                    for k in ("prompt", "completion", "total"):
                        if usage.get(k):
                            acc[k] = int(acc.get(k, 0)) + int(usage[k])
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
        # 用 dispatch 已知的租户/用户补齐 state（兼容调用方只传 messages 的情形）
        ustate = dict(unified_state) if hasattr(unified_state, "items") else {}
        ustate.setdefault("tenant_id", tenant_id)
        ustate.setdefault("user_id", user_id)
        ustate.setdefault("turn_id", turn_id)
        ustate.setdefault("trace_id", trace_id)
        initial = adapter.to_subgraph_input(
            unified_state=ustate, spec=spec, entry=entry, attachments=attachments
        )
        # 模板钩子：before_turn（幂等/记忆）→ 运行 → after_turn（记忆/审计）
        tpl = _template_of(agent_type)
        tpl_ctx = None
        if tpl is not None:
            tpl_ctx = tpl.turn_context(
                {
                    **initial,
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                    "turn_id": turn_id,
                    "trace_id": trace_id,
                    "session_id": (
                        unified_state.get("session_id", "")
                        if hasattr(unified_state, "get")
                        else ""
                    ),
                }
            )
            patch = await tpl.before_turn(tpl_ctx, initial)
            if patch:
                initial.update(patch)
        result = await orchestrator.run_agent(agent_type, partition, initial)
        if tpl is not None and tpl_ctx is not None:
            await tpl.after_turn(tpl_ctx, result)
            await tpl.audit(
                tpl_ctx, f"agent.{agent_type}.run", str(result.get("answer", ""))
            )
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

    # pipeline 由统一编排层直接调 orchestrator.run_plan（见 unified_graph._run_plan），
    # 不经过单 Agent 的 dispatch；此处不再提供旧 PipelineRunner 分支。
    raise ValueError(f"未知 execution_mode: {spec.execution_mode}")
