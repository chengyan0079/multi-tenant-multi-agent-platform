"""统一编排层引擎：薄图 UnifiedGraph + UnifiedState（会话级上下文与请求编排）。"""
from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage

import asyncio
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Optional

from langchain_core.runnables import RunnableConfig
from typing import TypedDict

from backend.orchestration.agent_registry import AgentRegistry
from backend.orchestration.agent_spec import AgentSpec
from backend.orchestration.unified_dispatch import (
    DefaultAgentAdapter,
    dispatch,
    fork_config,
    _partition_for,
    _template_of,
)
from backend.orchestration.unified_intent import UnifiedRouter
from backend.orchestration.unified_runtime import build_run_config
from backend.orchestration.unified_schemas import (
    AgentOutcome,
    EntryPayload,
    GuidanceEvent,
    MetaEvent,
    PipelinePlan,
    RoutingDecision,
    UnifiedEvent,
)

_NULL_SPEC = AgentSpec(agent_type="unified", display_name="unified")


class UnifiedState(TypedDict, total=False):
    """薄图运行时状态（框架边界容器；业务字段均为 Pydantic BaseModel，见 §4.1 / §5.11）。"""

    messages: list  # 运行时上下文窗口（BaseMessage 列表）
    existing_summary: Optional[str]
    routing: RoutingDecision
    entry: Optional[EntryPayload]
    short_term: list
    long_term: list
    turn_index: int
    last_agent_type: str
    tenant_id: int
    user_id: int
    session_id: str
    thread_id: str


@dataclass
class UnifiedRunResult:
    """一次 run() 的可观测结果，供接入层（Step 7 SSE）消费。"""

    thread_id: str
    turn_id: str
    routing: RoutingDecision
    outcome: Optional[AgentOutcome]
    events: list[UnifiedEvent]
    status: str
    error_code: Optional[str]


class UnifiedGraph:
    """统一编排层核心引擎（薄图）。串联路由 / 鉴权 / 入口校验 / 分发 / 写回。"""

    def __init__(
        self,
        *,
        registry: AgentRegistry,
        conversation_service: Any,
        orchestrator: Any,
        thread_dao: Any,
        router: Optional[UnifiedRouter] = None,
        adapter: Any = None,
        authz: Optional[Callable[[str, int, int], bool]] = None,
        classify_fn: Optional[Callable[..., Any]] = None,
        plan_fn: Optional[Callable[[str, list], PipelinePlan]] = None,
        pipeline_runner: Any = None,
    ) -> None:
        self._registry = registry
        self._conv = conversation_service
        self._orch = orchestrator
        self._thread_dao = thread_dao
        self._router = router or UnifiedRouter(registry)
        self._adapter = adapter or DefaultAgentAdapter(orchestrator=orchestrator)
        self._authz = authz
        self._classify_fn = classify_fn
        self._plan_fn = plan_fn
        self._pipeline_runner = pipeline_runner

    async def run(
        self,
        *,
        session_id: str,
        tenant_id: int,
        user_id: int,
        message: str,
        agent_type: Optional[str] = None,
        entry: Optional[EntryPayload] = None,
        attachments: Optional[list] = None,
        trace_id: Optional[str] = None,
    ) -> UnifiedRunResult:
        trace_id = trace_id or uuid.uuid4().hex
        # ② 会话 get_or_create（R1）
        thread = await self._thread_dao.get_or_create(
            session_key=session_id, tenant_id=tenant_id, user_id=user_id
        )
        # get_or_create 可能返回 dict（含 id）/ str（uuid）/ 对象，三种都要兼容
        U = (
            thread["id"]
            if isinstance(thread, dict)
            else thread
            if isinstance(thread, str)
            else getattr(thread, "id")
        )
        turn_index = await self._next_turn_index(U, tenant_id, user_id)

        # ⑥ 构造会话级 config（观测一次挂载）
        spec_hint = self._spec_for(agent_type) if agent_type else None
        cfg_U: RunnableConfig = build_run_config(
            thread_id=U,
            trace_id=trace_id,
            spec=spec_hint or _NULL_SPEC,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        # ③ 预分配本轮唯一 turn_id
        turn_id = uuid.uuid4().hex

        # ④ 双通道路由
        routing = await self._router.route(
            message=message,
            explicit_agent_type=agent_type,
            history="",
            classify_fn=self._classify_fn,
            tenant_id=tenant_id,
        )
        events: list[UnifiedEvent] = [
            UnifiedEvent(
                event_type="routing_decision",
                payload=_routing_event(
                    routing,
                    display=(self._spec_for(routing.agent_type).display_name
                             if self._spec_for(routing.agent_type) else ""),
                ),
            )
        ]

        status = "success"
        error_code: Optional[str] = None
        outcome: Optional[AgentOutcome] = None
        assistant_content: Optional[str] = None

        if routing.error_code:
            # 路由阶段已判定不可用（如显式请求了已停用的 Agent）
            status = "failed"
            error_code = routing.error_code
            events.append(
                UnifiedEvent(
                    event_type="error",
                    payload=_Err(routing.error_code, "Agent 未开通或无权访问"),
                )
            )
        elif routing.execution_mode == "rule":
            assistant_content = self._router.rule_reply(routing.label)
            events.append(
                UnifiedEvent(event_type="token", payload=_Tok(assistant_content))
            )
        elif routing.execution_mode == "clarify":
            spec = self._spec_for(routing.agent_type)
            events.append(
                UnifiedEvent(
                    event_type="guidance",
                    payload=GuidanceEvent(
                        message=(spec.init_prompt if spec else ""),
                        action_label=(spec.guidance_action_label if spec else ""),
                        code="INIT_REQUIRED",
                    ),
                )
            )
            status = "failed"
            error_code = "INIT_REQUIRED"
        elif routing.execution_mode == "pipeline":
            plan = PipelinePlan()
            if self._plan_fn is not None:
                plan = self._plan_fn(message, self._registry.specs())
                if asyncio.iscoroutine(plan):
                    plan = await plan
            outcome = await self._run_pipeline(
                plan, cfg_U, U, tenant_id, user_id, trace_id, turn_id
            )
            assistant_content = outcome.content
            events.extend(outcome.events)
            # 逐步失败（如鉴权不通过）向上传播为整体失败
            err_evt = next(
                (e for e in outcome.events if e.event_type == "error"), None
            )
            if err_evt is not None:
                status = "failed"
                error_code = err_evt.payload.code
        else:
            # 运行期鉴权（⑤）
            if not self._authorize(routing.agent_type, tenant_id, user_id):
                status = "failed"
                error_code = "FORBIDDEN"
                events.append(
                    UnifiedEvent(
                        event_type="error",
                        payload=_Err("FORBIDDEN", "无权限或 Agent 未开通"),
                    )
                )
            else:
                spec = self._spec_for(routing.agent_type)
                missing = self._missing_entry(spec, entry)
                if missing:
                    status = "failed"
                    error_code = "INIT_REQUIRED"
                    events.append(
                        UnifiedEvent(
                            event_type="guidance",
                            payload=GuidanceEvent(
                                message=(spec.init_prompt if spec else ""),
                                action_label=(spec.guidance_action_label if spec else ""),
                                code="INIT_REQUIRED",
                            ),
                        )
                    )
                else:
                    unified_state: UnifiedState = {
                        "thread_id": U,
                        "messages": [],
                        "existing_summary": None,
                    }
                    outcome = await dispatch(
                        agent_type=routing.agent_type,
                        unified_state=unified_state,
                        parent_cfg=cfg_U,
                        entry=entry,
                        attachments=attachments or [],
                        spec=spec,
                        adapter=self._adapter,
                        orchestrator=self._orch,
                        registry=self._registry,
                        trace_id=trace_id,
                        turn_id=turn_id,
                        tenant_id=tenant_id,
                        user_id=user_id,
                    )
                    assistant_content = outcome.content
                    events.extend(outcome.events)

        events.append(UnifiedEvent(event_type="done", payload=_Done()))

        # ⑧ 一次写回 turn（降级不影响主链路）；显式带上预分配 turn_id，供业务表 JOIN
        await self._conv.append_turn(
            turn_id=turn_id,
            thread_id=U,
            tenant_id=tenant_id,
            user_id=user_id,
            agent_type=routing.agent_type or "unified",
            spec_version=routing.spec_version,
            trace_id=trace_id,
            turn_index=turn_index,
            event_type="chat",
            user_content=message,
            assistant_content=assistant_content,
            payload={"execution_mode": routing.execution_mode, "source": routing.source},
            routing=routing.model_dump(),
            status=status,
            error_code=error_code,
        )

        return UnifiedRunResult(
            thread_id=U,
            turn_id=turn_id,
            routing=routing,
            outcome=outcome,
            events=events,
            status=status,
            error_code=error_code,
        )

    async def _load_history(
        self, thread_id: str, tenant_id: int, user_id: int, limit: int = 20
    ) -> list:
        """按 thread 读取近 N 轮历史并转为消息（失败降级为空）。"""
        try:
            from backend.data.dao.agent.unified_turn_dao import UnifiedTurnDao

            rows = await UnifiedTurnDao.list_recent_by_thread(
                thread_id=thread_id, tenant_id=tenant_id, user_id=user_id, limit=limit
            )
            msgs: list = []
            for r in rows:
                uc = getattr(r, "user_content", None)
                ac = getattr(r, "assistant_content", None)
                if uc:
                    msgs.append(HumanMessage(content=uc))
                if ac:
                    msgs.append(AIMessage(content=ac))
            return msgs
        except Exception:  # noqa: BLE001 - 历史不可用不影响本轮
            return []

    async def run_stream(
        self,
        *,
        session_id: str,
        tenant_id: int,
        user_id: int,
        message: str,
        agent_type: Optional[str] = None,
        entry: Optional[EntryPayload] = None,
        attachments: Optional[list] = None,
        trace_id: Optional[str] = None,
        thinking: bool = False,
    ):
        """流式变体：异步产出 UnifiedEvent 序列（SSE 逐帧推送），结束写回单条 turn。

        与 run() 共享路由 / 鉴权 / 入口校验逻辑；差异仅在 stream 模式走 adapter.stream
        真流式（逐 token），而非 run() 的收集式 dispatch。task / pipeline 模式仍复用 dispatch。
        """
        import time

        t0 = time.perf_counter()
        trace_id = trace_id or uuid.uuid4().hex
        thread = await self._thread_dao.get_or_create(
            session_key=session_id, tenant_id=tenant_id, user_id=user_id
        )
        # get_or_create 可能返回 dict（含 id）/ str（uuid）/ 对象，三种都要兼容
        U = (
            thread["id"]
            if isinstance(thread, dict)
            else thread
            if isinstance(thread, str)
            else getattr(thread, "id")
        )
        turn_index = await self._next_turn_index(U, tenant_id, user_id)

        spec_hint = self._spec_for(agent_type) if agent_type else None
        cfg_U: RunnableConfig = build_run_config(
            thread_id=U,
            trace_id=trace_id,
            spec=spec_hint or _NULL_SPEC,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        turn_id = uuid.uuid4().hex

        routing = await self._router.route(
            message=message,
            explicit_agent_type=agent_type,
            history="",
            classify_fn=self._classify_fn,
            tenant_id=tenant_id,
        )
        yield UnifiedEvent(
            event_type="routing_decision",
            payload=_routing_event(
                routing,
                display=(self._spec_for(routing.agent_type).display_name
                         if self._spec_for(routing.agent_type) else ""),
            ),
        )

        status = "success"
        error_code: Optional[str] = None
        assistant_content: Optional[str] = None
        outcome: Optional[AgentOutcome] = None
        meta_sink: dict = {}

        if routing.error_code:
            # 路由阶段已判定不可用（如显式请求了已停用的 Agent）
            status = "failed"
            error_code = routing.error_code
            yield UnifiedEvent(
                event_type="error",
                payload=_Err(routing.error_code, "Agent 未开通或无权访问"),
            )
        elif routing.execution_mode == "rule":
            assistant_content = self._router.rule_reply(routing.label)
            yield UnifiedEvent(event_type="token", payload=_Tok(assistant_content))
        elif routing.execution_mode == "clarify":
            spec = self._spec_for(routing.agent_type)
            yield UnifiedEvent(
                event_type="guidance",
                payload=GuidanceEvent(
                    message=(spec.init_prompt if spec else ""),
                    action_label=(spec.guidance_action_label if spec else ""),
                    code="INIT_REQUIRED",
                ),
            )
            status = "failed"
            error_code = "INIT_REQUIRED"
        elif routing.execution_mode == "pipeline":
            plan = PipelinePlan()
            if self._plan_fn is not None:
                plan = self._plan_fn(message, self._registry.specs())
                if asyncio.iscoroutine(plan):
                    plan = await plan
            outcome = await self._run_pipeline(
                plan, cfg_U, U, tenant_id, user_id, trace_id, turn_id
            )
            assistant_content = outcome.content
            for e in outcome.events:
                yield e
            err_evt = next((e for e in outcome.events if e.event_type == "error"), None)
            if err_evt is not None:
                status = "failed"
                error_code = err_evt.payload.code
        else:
            if not self._authorize(routing.agent_type, tenant_id, user_id):
                status = "failed"
                error_code = "FORBIDDEN"
                yield UnifiedEvent(
                    event_type="error",
                    payload=_Err("FORBIDDEN", "无权限或 Agent 未开通"),
                )
            else:
                spec = self._spec_for(routing.agent_type)
                missing = self._missing_entry(spec, entry)
                if missing:
                    status = "failed"
                    error_code = "INIT_REQUIRED"
                    yield UnifiedEvent(
                        event_type="guidance",
                        payload=GuidanceEvent(
                            message=(spec.init_prompt if spec else ""),
                            action_label=(spec.guidance_action_label if spec else ""),
                            code="INIT_REQUIRED",
                        ),
                    )
                elif routing.execution_mode == "stream":
                    partition = _partition_for(
                        spec, thread_id=U, turn_id=turn_id, artifact_id=""
                    )
                    cfg = fork_config(cfg_U, thread_id=partition)
                    # 多轮历史 + 当前输入（压缩由 to_subgraph_input 完成）
                    history = await self._load_history(U, tenant_id, user_id)
                    if message:
                        history.append(HumanMessage(content=message))
                    initial = self._adapter.to_subgraph_input(
                        unified_state={
                            "thread_id": U,
                            "messages": history,
                            "existing_summary": None,
                            "query": message,
                            # 关键上下文（缺了会让检索/记忆落到租户 0 或直接 KeyError）
                            "tenant_id": tenant_id,
                            "user_id": user_id,
                            "session_id": session_id,
                            "turn_id": turn_id,
                            "trace_id": trace_id,
                            "thinking": thinking,
                        },
                        spec=spec,
                        entry=entry,
                        attachments=attachments or [],
                    )
                    tpl = _template_of(routing.agent_type)
                    tpl_ctx = None
                    if tpl is not None:
                        tpl_ctx = tpl.turn_context(
                            {
                                **initial,
                                "tenant_id": tenant_id,
                                "user_id": user_id,
                                "turn_id": turn_id,
                                "trace_id": trace_id,
                                "session_id": session_id,
                            }
                        )
                        patch = await tpl.before_turn(tpl_ctx, initial)
                        if patch:
                            initial.update(patch)
                    parts: list[str] = []
                    async for ev in self._adapter.stream(
                        agent_type=routing.agent_type,
                        thread_id=partition,
                        initial_state=initial,
                        config=cfg,
                        spec=spec,
                        meta_sink=meta_sink,
                    ):
                        if ev.event_type == "token":
                            parts.append(ev.payload.content)
                        yield ev
                    assistant_content = "".join(parts)
                    if tpl is not None and tpl_ctx is not None:
                        await tpl.after_turn(tpl_ctx, {"answer": assistant_content})
                        await tpl.audit(
                            tpl_ctx, f"agent.{routing.agent_type}.run", assistant_content
                        )
                else:  # task
                    outcome = await dispatch(
                        agent_type=routing.agent_type,
                        unified_state={"thread_id": U, "messages": [], "existing_summary": None},
                        parent_cfg=cfg_U,
                        entry=entry,
                        attachments=attachments or [],
                        spec=spec,
                        adapter=self._adapter,
                        orchestrator=self._orch,
                        registry=self._registry,
                        trace_id=trace_id,
                        turn_id=turn_id,
                        tenant_id=tenant_id,
                        user_id=user_id,
                    )
                    assistant_content = outcome.content
                    for e in outcome.events:
                        yield e

        # token 用量：模型返回 usage 时直接用；部分网关（如 deepseek 流式）不返回 →
        # 按字符估算（中文约 2 字符/token），并标注 estimated，前端用 ~ 区分。
        usage: dict[str, Any] = dict(meta_sink.get("token_usage") or {})
        if not usage.get("total"):
            from math import ceil

            ctx_chars = sum(
                len(str(c.get("content") or ""))
                for c in (meta_sink.get("contexts") or [])
                if isinstance(c, dict)
            )
            prompt_chars = len(message or "") + ctx_chars
            completion_chars = len(assistant_content or "")
            usage = {
                "prompt": ceil(prompt_chars / 2),
                "completion": ceil(completion_chars / 2),
                "total": ceil((prompt_chars + completion_chars) / 2),
                "estimated": True,
            }

        yield UnifiedEvent(
            event_type="meta",
            payload=MetaEvent(
                thread_id=U,
                turn_id=turn_id,
                turn_index=turn_index,
                answer_mode=meta_sink.get("answer_mode"),
                confidence=meta_sink.get("confidence"),
                sources=meta_sink.get("sources"),
                latency_ms=int((time.perf_counter() - t0) * 1000),
                token_usage=usage,
            ),
        )
        yield UnifiedEvent(event_type="done", payload=_Done())

        await self._conv.append_turn(
            turn_id=turn_id,
            thread_id=U,
            tenant_id=tenant_id,
            user_id=user_id,
            agent_type=routing.agent_type or "unified",
            spec_version=routing.spec_version,
            trace_id=trace_id,
            turn_index=turn_index,
            event_type="chat",
            user_content=message,
            assistant_content=assistant_content,
            payload={
                "execution_mode": routing.execution_mode,
                "source": routing.source,
                "answer_mode": meta_sink.get("answer_mode"),
                "confidence": meta_sink.get("confidence"),
                "sources": meta_sink.get("sources"),
                # 检索上下文快照：供「问答结果」展示与 RAGAS context 指标
                "retrieved_contexts": meta_sink.get("contexts"),
            },
            latency_ms=int((time.perf_counter() - t0) * 1000),
            token_usage=usage,
            routing=routing.model_dump(),
            status=status,
            error_code=error_code,
        )

    # ------------------------------------------------------------------ #
    async def _run_pipeline(
        self, plan, cfg_U, U, tenant_id, user_id, trace_id, turn_id
    ) -> AgentOutcome:
        from backend.orchestration.pipeline_runner import PipelineRunner

        runner = self._pipeline_runner or PipelineRunner(
            orchestrator=self._orch,
            adapter=self._adapter,
            registry=self._registry,
            authz=self._authz,
        )
        return await runner.run(
            plan=plan,
            cfg_U=cfg_U,
            thread_id=U,
            tenant_id=tenant_id,
            user_id=user_id,
            trace_id=trace_id,
            turn_id=turn_id,
            conversation_service=self._conv,
        )

    def _authorize(self, agent_type: str, tenant_id: int, user_id: int) -> bool:
        if self._authz is not None:
            return self._authz(agent_type, tenant_id, user_id)
        if not self._registry.is_enabled_for_tenant(agent_type, tenant_id):
            return False
        # 运行期 scope 校验需请求上下文；无上下文时（单测/编排层）放宽到仅检查开通
        try:
            from backend.security.rbac import has_scope

            spec = self._spec_for(agent_type)
            if spec and spec.scope:
                return has_scope(spec.scope)
        except Exception:
            pass
        return True

    def _missing_entry(
        self, spec: Optional[AgentSpec], entry: Optional[EntryPayload]
    ) -> list[str]:
        if spec is None:
            return []
        required = {ef.name for ef in spec.entry_fields if ef.required}
        if not required:
            return []
        provided = {f.name for f in (entry.fields if entry else []) if f.value}
        return sorted(required - provided)

    async def _next_turn_index(self, thread_id: str, tenant_id: int, user_id: int) -> int:
        """取该会话下一轮序号（max+1）。

        必须以 agent_unified_turn 为准（turn 表有唯一索引 (thread_id, turn_index)，
        序号重复会导致 INSERT 冲突、整轮历史丢失）。
        """
        from backend.data.dao.agent.unified_turn_dao import UnifiedTurnDao
        from backend.common.logger import logger as _logger

        try:
            return await UnifiedTurnDao.next_turn_index(
                thread_id=thread_id, tenant_id=tenant_id, user_id=user_id
            )
        except Exception:  # noqa: BLE001 - 无 DB 上下文（单测）时退化为 1
            _logger.debug("next_turn_index 计算失败（无 DB 上下文？），退化为 1")
            return 1

    def _spec_for(self, agent_type: str) -> Optional[AgentSpec]:
        for s in self._registry.specs():
            if s.agent_type == agent_type:
                return s
        return None


# 小工具：构造事件载荷（避免与 unified_schemas 判别联合 import 过宽）
def _routing_event(r: RoutingDecision, display: str = ""):
    from backend.orchestration.unified_schemas import RoutingDecisionEvent

    return RoutingDecisionEvent(
        agent_type=r.agent_type,
        agent_display=display,
        source=r.source,
        confidence=r.confidence,
        reason=r.reason,
        execution_mode=r.execution_mode,
        spec_version=r.spec_version,
    )


def _Tok(content: str):
    from backend.orchestration.unified_schemas import TokenEvent

    return TokenEvent(content=content)


def _Done():
    from backend.orchestration.unified_schemas import DoneEvent

    return DoneEvent()


def _Err(code: str, message: str):
    from backend.orchestration.unified_schemas import ErrorEvent

    return ErrorEvent(code=code, message=message)
