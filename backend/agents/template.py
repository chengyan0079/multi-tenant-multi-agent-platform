"""Agent 模板抽象（生产级）：多轮 / 记忆 / 上下文压缩 / 提示词 / 幂等 / HITL / 审计 / 可观测。

新增 Agent 只需继承 ``AgentTemplate`` 并声明 ``metadata()`` 与 ``flow()``；
图装配与生产级钩子由模板统一提供。既有 qa 等 Agent 保留各自 build_graph，不被强制迁移。
"""

from __future__ import annotations

import asyncio


class ToolNotEnabled(RuntimeError):
    """工具未在该租户启用（应结束流程并向前端提示）。"""

from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator, Optional, TypedDict

from langgraph.graph import END, START, StateGraph

from backend.agents.base import Agent
from backend.app_state import app_state
from backend.orchestration.agent_spec import AgentSpec


class BaseAgentState(TypedDict, total=False):
    """所有 Agent 的公共状态字段。"""

    messages: list
    tenant_id: int
    user_id: int
    session_id: str
    turn_id: str
    trace_id: str
    query: str
    existing_summary: Optional[str]
    approval: Optional[dict]
    approval_gate: Optional[str]


@dataclass(frozen=True)
class TurnContext:
    """一轮对话的运行上下文：幂等 / 隔离 / 观测 / 恢复的键。"""

    tenant_id: int
    user_id: int
    session_id: str
    turn_id: str
    thread_id: str
    agent_type: str
    trace_id: str = ""

    @property
    def idempotency_key(self) -> str:
        return f"{self.agent_type}:{self.thread_id}:{self.turn_id}"


def build_thread_id(tenant_id: int, user_id: int, session_id: str) -> str:
    """会话级 thread_id：多轮共享 checkpoint，租户/用户维度隔离。"""
    return f"t{tenant_id}:u{user_id}:{session_id}"


@dataclass
class FlowSpec:
    """Agent 图流程声明（节点 / 边 / 条件边 / 入口 / 终止节点 / Send 扇出）。"""

    nodes: dict[str, Callable] = field(default_factory=dict)
    entry: str = ""
    edges: list[tuple[str, str]] = field(default_factory=list)
    conditional: list[tuple[str, Callable, dict[str, str]]] = field(default_factory=list)
    end_nodes: list[str] = field(default_factory=list)
    entry_from_start: bool = True
    # Send 扇出：(源节点, 返回 [Send(...)] 的函数)，用于并行分支
    send_fanout: list[tuple[str, Callable]] = field(default_factory=list)


# ---------- 上下文压缩 ----------


def estimate_tokens(text: str) -> int:
    """粗略 token 估算（中英混合按字符/3）。可替换为 tiktoken 精确计数。"""
    return max(1, len(text) // 3)


def truncate_text(text: str, max_chars: int, keep_tail: int = 200) -> str:
    """单条超长文本截取：保留开头与结尾，中间省略（避免丢首尾关键信息）。"""
    if len(text) <= max_chars:
        return text
    head = max(0, max_chars - keep_tail)
    return text[:head] + "\n...(已截断)..." + text[-keep_tail:]


def compress_messages(messages: list, window: int, budget_tokens: int) -> list:
    """滑动窗口 + token 预算压缩。

    1) 先保留最近 ``window`` 条（滑动窗口）；
    2) 从旧到新累计，超出 ``budget_tokens`` 的早期消息丢弃；
    3) 单条超长由调用方 ``truncate_text`` 截取。
    """
    recent = list(messages[-window:]) if window > 0 else list(messages)
    total = 0
    kept: list = []
    for msg in reversed(recent):
        text = str(getattr(msg, "content", msg))
        t = estimate_tokens(text)
        if kept and total + t > budget_tokens:
            break
        kept.append(msg)
        total += t
    kept.reverse()
    return kept


# ---------- 观测 / 审计 ----------


@contextmanager
def trace_span(name: str, **attrs: Any) -> Iterator[None]:
    """结构化 trace span（日志埋点；Langfuse 由 callback 另采）。"""
    from backend.common.logger import get_logger

    log = get_logger("agent.span")
    log.info(f"span.start {name}", **attrs)
    try:
        yield
    except Exception as exc:  # noqa: BLE001
        log.warning(f"span.error {name}", error=str(exc), **attrs)
        raise
    finally:
        log.info(f"span.end {name}", **attrs)


def get_langfuse_handler() -> Any:
    """按配置返回 Langfuse CallbackHandler；未配置/未安装降级为 None。"""
    try:
        s = app_state.settings
        public_key = getattr(s, "langfuse_public_key", "") or ""
        secret_key = getattr(s, "langfuse_secret_key", "") or ""
        host = getattr(s, "langfuse_host", "") or ""
        if not (public_key and secret_key):
            return None
        from langfuse.callback import CallbackHandler  # type: ignore

        return CallbackHandler(public_key=public_key, secret_key=secret_key, host=host)
    except Exception:  # noqa: BLE001 - 观测不可用不影响主链路
        return None


def hitl_node(gate: str, payload_fn: Optional[Callable] = None) -> Callable:
    """HITL 门禁节点：``interrupt(gate)`` 暂停，等待人工 ``Command(resume)``。"""

    def _node(state: dict) -> dict:
        from langgraph.types import interrupt

        payload = payload_fn(state) if payload_fn else {"gate": gate}
        decision = interrupt({"gate": gate, "payload": payload})
        return {"approval": decision, "approval_gate": gate}

    return _node


class AgentTemplate(Agent):
    """通用 Agent 模板（生产级）。"""

    state_cls: type = BaseAgentState
    prompts: dict[str, str] = {}
    context_token_budget: int = 4000
    history_window: int = 6
    hitl_timeout_s: int = 1800
    max_iterations: int = 8  # 单轮图循环上限（防死循环）

    def input_schema(self) -> Optional[dict]:
        return None

    def flow(self) -> FlowSpec:  # pragma: no cover - 子类实现
        raise NotImplementedError(f"{type(self).__name__} 必须实现 flow()")

    def _debug_wrap(self, name: str, fn: Any) -> Any:
        """节点级 debug 日志（进入/退出/耗时/异常），用于开发联调观察。"""
        import functools
        import json
        import time

        from backend.common.logger import get_logger

        log = get_logger(f"agent.{self.agent_type}")

        def _brief(value: Any) -> str:
            """节点返回结构摘要（截断，避免 messages/大对象刷屏）。"""
            try:
                text = json.dumps(value, ensure_ascii=False, default=str)
            except Exception:  # noqa: BLE001
                text = str(value)
            return text if len(text) <= 800 else text[:800] + "...(truncated)"

        if asyncio.iscoroutinefunction(fn):

            @functools.wraps(fn)
            async def _async_node(*args: Any, **kwargs: Any) -> Any:
                log.debug(f"node enter: {name}")
                t0 = time.perf_counter()
                try:
                    result = await fn(*args, **kwargs)
                except Exception as exc:  # noqa: BLE001
                    log.error(
                        f"node error: {name} ({time.perf_counter() - t0:.0f}ms) {exc}"
                    )
                    raise
                log.debug(
                    f"node exit: {name} ({time.perf_counter() - t0:.0f}ms) out={_brief(result)}"
                )
                return result

            return _async_node

        @functools.wraps(fn)
        def _sync_node(*args: Any, **kwargs: Any) -> Any:
            log.debug(f"node enter: {name}")
            t0 = time.perf_counter()
            try:
                result = fn(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001
                log.error(f"node error: {name} ({time.perf_counter() - t0:.0f}ms) {exc}")
                raise
            log.debug(
                f"node exit: {name} ({time.perf_counter() - t0:.0f}ms) out={_brief(result)}"
            )
            return result

        return _sync_node

    def build_graph(self) -> Any:
        spec = self.flow()
        builder = StateGraph(self.state_cls)
        for name, fn in spec.nodes.items():
            builder.add_node(name, self._debug_wrap(name, fn))
        if spec.entry_from_start and spec.entry:
            builder.add_edge(START, spec.entry)
        for src, dst in spec.edges:
            builder.add_edge(src, dst)
        for src, route_fn, mapping in spec.conditional:
            builder.add_conditional_edges(src, route_fn, mapping)
        for src, fanout_fn in spec.send_fanout:
            builder.add_conditional_edges(src, fanout_fn)
        for node in spec.end_nodes:
            builder.add_edge(node, END)
        return builder.compile(checkpointer=app_state.checkpointer)

    # ---------- 生产级钩子 ----------

    def turn_context(self, state: dict) -> TurnContext:
        tenant_id = int(state.get("tenant_id", 0))
        user_id = int(state.get("user_id", 0))
        session_id = str(state.get("session_id") or "")
        return TurnContext(
            tenant_id=tenant_id,
            user_id=user_id,
            session_id=session_id,
            turn_id=str(state.get("turn_id") or ""),
            thread_id=build_thread_id(tenant_id, user_id, session_id),
            agent_type=self.agent_type,
            trace_id=str(state.get("trace_id") or ""),
        )

    async def before_turn(self, ctx: TurnContext, state: dict) -> dict:
        """轮次开始：幂等去重 / 同 thread 串行 / 加载记忆与摘要（默认空实现）。"""
        return {}

    async def after_turn(self, ctx: TurnContext, state: dict) -> None:
        """轮次结束：写长期记忆 / 会话摘要 / 审计（默认空实现）。"""

    def compress_context(self, state: dict) -> list:
        """上下文压缩：滑动窗口 + token 预算（超预算丢弃早期消息）。"""
        return compress_messages(
            state.get("messages") or [], self.history_window, self.context_token_budget
        )

    def assemble_context(self, state: dict) -> str:
        """上下文组装（默认只返回 query；子类覆盖为 system+记忆+RAG+历史+输入）。"""
        return str(state.get("query") or "")

    def render_prompt(self, name: str, **kwargs: Any) -> str:
        template = self.prompts.get(name)
        if not template:
            raise KeyError(f"{self.agent_type} 缺少提示词: {name}")
        return template.format(**kwargs)

    def invoke_config(self, ctx: TurnContext) -> dict:
        """LangChain 调用配置：Langfuse callback + trace/租户元数据。"""
        handler = get_langfuse_handler()
        return {
            "callbacks": [handler] if handler else [],
            "recursion_limit": self.max_iterations,
            "metadata": {
                "trace_id": ctx.trace_id,
                "tenant_id": ctx.tenant_id,
                "user_id": ctx.user_id,
                "agent_type": ctx.agent_type,
                "session_id": ctx.session_id,
                "turn_id": ctx.turn_id,
            },
        }

    async def audit(self, ctx: TurnContext, action: str, result: str = "", **extra: Any) -> None:
        """结构化审计（谁/什么/何时/结果/trace）；失败降级不阻断。"""
        try:
            from backend.common.logger import get_logger

            get_logger("agent.audit").info(
                "agent.audit",
                agent_type=ctx.agent_type,
                tenant_id=ctx.tenant_id,
                user_id=ctx.user_id,
                thread_id=ctx.thread_id,
                turn_id=ctx.turn_id,
                trace_id=ctx.trace_id,
                action=action,
                result=result,
                **extra,
            )
        except Exception:  # noqa: BLE001
            pass

    # ---------- 工具接入 / 循环 / 降级 ----------

    async def available_tools(self, ctx: TurnContext) -> list[dict]:
        """该租户已注册且 enabled 的工具（agent_tool）。"""
        try:
            from backend.data.dao.agent.tool_dao import ToolDao

            rows, _ = await ToolDao.list_paged(
                tenant_id=ctx.tenant_id, enabled=True, page=1, page_size=200
            )
            return rows
        except Exception:  # noqa: BLE001 - 工具不可用不影响主链路
            return []

    async def load_tool_config(self, ctx: TurnContext, name: str) -> dict:
        """取该租户某工具的运行配置（仅 enabled 工具返回）。"""
        from backend.data.dao.agent.tool_dao import get_tool_config

        return await get_tool_config(name, ctx.tenant_id)

    async def call_tool(
        self,
        ctx: TurnContext,
        name: str,
        *,
        fallback: Optional[Callable] = None,
        **kwargs: Any,
    ) -> Any:
        """调用该租户启用的工具；未启用则抛 ToolNotEnabled（结束流程，不降级）。"""
        from backend.app_state import app_state

        reg = getattr(app_state, "plugin_registry", None)
        if reg is not None and not reg.is_tool_enabled_for_tenant(ctx.tenant_id, name):
            raise ToolNotEnabled(f"工具 {name} 未在租户 {ctx.tenant_id} 启用")
        try:
            from backend.app_state import app_state

            reg = getattr(app_state, "plugin_registry", None)
            if reg is None:
                raise RuntimeError("plugin_registry 未就绪")
            return await reg.call(name, **kwargs)
        except Exception as exc:  # noqa: BLE001
            await self.audit(ctx, f"tool.{name}.failed", str(exc))
            if fallback is not None:
                return await fallback(**kwargs)
            return {"degraded": True, "tool": name, "error": str(exc)}

    def loop_guard(self, state: dict, key: str = "_loop_count") -> int:
        """循环计数守卫：返回自增计数；超 max_iterations 抛错（调用方降级）。"""
        n = int(state.get(key, 0)) + 1
        if n > self.max_iterations:
            raise RuntimeError(f"{self.agent_type} 循环超过上限 {self.max_iterations}")
        return n

    def should_interrupt(self, state: dict) -> bool:
        return False

    def export_graph_png(self, path: str | None = None) -> str:
        """导出本 Agent 的 LangGraph 图为 PNG；返回产物路径。

        优先 graphviz `draw_png`，失败回退 `draw_mermaid_png`，再失败输出 `.mmd` 文本。
        每个 Agent 只需 ``AgentClass().export_graph_png("xxx_graph.png")`` 即可出图。
        """
        import pathlib

        out = path or f"{self.agent_type}_graph.png"
        drawn = self.build_graph().get_graph()
        try:
            drawn.draw_png(out)
            return str(pathlib.Path(out))
        except Exception:  # noqa: BLE001 - graphviz 不可用回退
            try:
                drawn.draw_mermaid_png(output_file_path=out)
                return str(pathlib.Path(out))
            except Exception:  # noqa: BLE001 - 网络/依赖不可用回退文本
                mmd = pathlib.Path(out).with_suffix(".mmd")
                mmd.write_text(drawn.draw_mermaid(), encoding="utf-8")
                return str(mmd)
