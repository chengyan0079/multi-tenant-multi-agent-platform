"""编排器：单 Agent 直达 + 多 Agent 串联调度，HITL 由图的 interrupt/resume 承载。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from backend.app_state import app_state
from backend.common.logger import get_logger
from backend.orchestration.agent_registry import AgentRegistry
from backend.observability.exception import TenantError
from backend.observability.tracing import tracing

logger = get_logger("orchestrator")


class Orchestrator:
    """编排内核：单 Agent 直达 + 多 Agent 串联。"""

    def __init__(self, registry: AgentRegistry) -> None:
        self._registry = registry

    async def start(self) -> None:
        return None

    async def run_agent(
        self, agent_type: str, thread_id: str, inputs: Dict[str, Any]
    ) -> Dict[str, Any]:
        """单 Agent 直达：取图 + checkpointer 执行，返回最终 state。"""
        meta = self._registry.get(agent_type)
        if not meta.enabled:
            raise TenantError(f"Agent 未开通: {agent_type}")
        graph = meta.build_graph()
        # checkpointer 由 CheckpointerManager 注入，支持多轮与 HITL 恢复
        cfg = tracing.with_callbacks({"configurable": {"thread_id": thread_id}})
        # 收集本轮 LLM token 用量（非流式 agent 卡片展示用）
        from backend.common.llm.token_usage import TokenUsageCallback

        usage_cb = TokenUsageCallback()
        cfg["callbacks"] = list(cfg.get("callbacks") or []) + [usage_cb]
        result = await graph.ainvoke(inputs, config=cfg)
        out = dict(result)
        stats = usage_cb.as_dict()
        if stats.get("usage_available"):
            out["token_usage"] = {
                "prompt": stats.get("prompt_tokens", 0),
                "completion": stats.get("completion_tokens", 0),
                "total": stats.get("total_tokens", 0),
            }
        return out

    async def run_agent_stream(
        self,
        agent_type: str,
        thread_id: str,
        inputs: Dict[str, Any],
        config: Optional[Dict[str, Any]] = None,
    ):
        """单 Agent 真流式：按 LangGraph v2 事件流产出，由 adapter 过滤映射为统一事件。

        仅产出原始事件（on_chat_model_stream / on_chain_start / on_chain_end ...），
        不在此做业务翻译，保持编排内核与协议解耦。
        """
        meta = self._registry.get(agent_type)
        if not meta.enabled:
            raise TenantError(f"Agent 未开通: {agent_type}")
        graph = meta.build_graph()
        cfg = tracing.with_callbacks(
            config or {"configurable": {"thread_id": thread_id}}
        )
        async for event in graph.astream_events(inputs, config=cfg, version="v2"):
            yield event

    async def run_pipeline(
        self, pipeline_plan: List[str], thread_id: str, inputs: Dict[str, Any]
    ) -> Dict[str, Any]:
        """多 Agent 串联：依次执行，前一步 state 透传为下一步输入。"""
        carry: Dict[str, Any] = dict(inputs)
        for agent_type in pipeline_plan:
            logger.info(f"pipeline 步骤: {agent_type}")
            carry = await self.run_agent(agent_type, f"{thread_id}:{agent_type}", carry)
        return carry

    async def run_parallel(
        self, agent_types: List[str], thread_id: str, inputs: Dict[str, Any]
    ) -> Dict[str, Any]:
        """多 Agent 并发：各自独立 state，结果汇总（单分支失败不扩散）。"""
        import asyncio

        async def _one(agent_type: str) -> Dict[str, Any]:
            try:
                return await self.run_agent(
                    agent_type, f"{thread_id}:{agent_type}", dict(inputs)
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"parallel 分支失败: {agent_type} - {exc}")
                return {"error": str(exc)}

        results = await asyncio.gather(*(_one(a) for a in agent_types))
        return {
            "parallel": {a: r for a, r in zip(agent_types, results)},
            "agents": list(agent_types),
        }

    async def run_plan(
        self, plan: Dict[str, Any], thread_id: str, inputs: Dict[str, Any]
    ) -> Dict[str, Any]:
        """编排计划 DSL 执行器（支持嵌套组合）。

        step.type:
        - agent:    {"agent": "db_review"}
        - parallel: {"agents": ["qa", "db_review"]}
        - sequence: {"steps": [step, ...]}
        - branch:   {"on": "risk_level", "cases": {"low": step, ...}, "default": step}
        - loop:     {"step": step, "max": 3}（state.done=true 提前退出）

        carry 里维护 ``_step_results``（每步摘要）与 ``_current_step``（停在第几步）；
        遇到 HITL ``__interrupt__`` 或人工拒绝（rejected/blocked）立即停住，不跑后续步骤，
        由统一入口发 interrupt 事件 / 终止整链。
        """
        carry = dict(inputs)
        carry.setdefault("_step_results", [])
        carry.setdefault("_current_step", 0)
        return await self._exec_step(plan, thread_id, carry)

    @staticmethod
    def _is_halted(carry: Dict[str, Any]) -> bool:
        """本步执行后是否应停止后续步骤：HITL 挂起或人工否决。"""
        if "__interrupt__" in carry:
            return True
        return str(carry.get("status") or carry.get("release_status") or "") in {
            "rejected",
            "blocked",
            "pending_approval",
        }

    async def _exec_step(
        self, step: Dict[str, Any], thread_id: str, carry: Dict[str, Any]
    ) -> Dict[str, Any]:
        t = (step or {}).get("type")
        if t == "agent":
            agent = step["agent"]
            try:
                meta = self._registry.get(agent)
            except KeyError:
                meta = None
            if meta is None or not meta.enabled:
                raise TenantError(f"pipeline 步骤指向未注册或未启用的 Agent: {agent}")
            turn_id = str(carry.get("turn_id") or "")
            partition = f"{thread_id}:{agent}:{turn_id}" if turn_id else f"{thread_id}:{agent}"
            res = await self.run_agent(agent, partition, dict(carry))
            merged = {**carry, **res}
            idx = len(merged.get("_step_results") or []) + 1
            merged["_current_step"] = idx
            merged.setdefault("_step_results", []).append(
                {
                    "step": idx,
                    "agent_type": agent,
                    "content": str(res.get("content") or res.get("answer") or ""),
                    "status": res.get("status") or res.get("release_status") or "",
                    "interrupted": "__interrupt__" in res,
                }
            )
            return merged
        if t == "parallel":
            if self._is_halted(carry):
                return carry
            res = await self.run_parallel(step["agents"], thread_id, dict(carry))
            return {**carry, **res}
        if t == "sequence":
            cur = dict(carry)
            for sub in step.get("steps") or []:
                cur = await self._exec_step(sub, thread_id, cur)
                if self._is_halted(cur):
                    break
            return cur
        if t == "branch":
            key = str(carry.get(step.get("on")))
            nxt = (step.get("cases") or {}).get(key) or step.get("default")
            if not nxt:
                return carry
            return await self._exec_step(nxt, thread_id, carry)
        if t == "loop":
            cur = dict(carry)
            for _ in range(int(step.get("max") or 3)):
                if cur.get("done") or self._is_halted(cur):
                    break
                cur = await self._exec_step(step["step"], thread_id, cur)
            return cur
        logger.warning(f"run_plan 未知 step.type: {t}")
        return carry

    async def update_state(
        self, agent_type: str, thread_id: str, values: Dict[str, Any]
    ) -> None:
        """把统计信息写进图状态（跨请求累计 token/耗时，HITL 恢复后合并输出）。"""
        meta = self._registry.get(agent_type)
        graph = meta.build_graph()
        cfg = {"configurable": {"thread_id": thread_id}}
        await graph.aupdate_state(cfg, values)

    async def get_state(self, agent_type: str, thread_id: str) -> Dict[str, Any]:
        """取图当前状态（用于流式结束后判断是否 interrupt）。"""
        meta = self._registry.get(agent_type)
        graph = meta.build_graph()
        cfg = {"configurable": {"thread_id": thread_id}}
        snapshot = await graph.aget_state(cfg)
        return dict(snapshot.values or {})

    async def astream_resume(self, agent_type: str, thread_id: str, value: Dict[str, Any]):
        """HITL 恢复后继续真流式（Command(resume) + astream_events）。"""
        from langgraph.types import Command

        meta = self._registry.get(agent_type)
        graph = meta.build_graph()
        cfg = tracing.with_callbacks({"configurable": {"thread_id": thread_id}})
        payload = value if isinstance(value, Command) else Command(resume=value)
        async for event in graph.astream_events(payload, config=cfg, version="v2"):
            yield event

    async def resume(
        self, agent_type: str, thread_id: str, value: Dict[str, Any]
    ) -> Dict[str, Any]:
        """HITL 恢复：向被 interrupt() 挂起的图注入决策后继续。"""
        from langgraph.types import Command

        meta = self._registry.get(agent_type)
        graph = meta.build_graph()
        cfg = tracing.with_callbacks({"configurable": {"thread_id": thread_id}})
        payload = value if isinstance(value, Command) else Command(resume=value)
        result = await graph.ainvoke(payload, config=cfg)
        return dict(result)

    async def stop(self) -> None:
        return None
