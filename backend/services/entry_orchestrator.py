"""入口编排：意图 → 流程（A 单点 / B 串行 / C 并行 / D 条件）执行。

- A single：单 Agent 直连；
- B sequential：按序串联（前一步 state 透传）；
- C parallel：多 Agent 并发（结果汇总）；
- D branch/clarify：返回候选，由前端/用户选择（不强行执行）。
"""

from __future__ import annotations

from typing import Any

from backend.app_state import app_state
from backend.common.logger import get_logger
from backend.services.intent_router import classify_intent

logger = get_logger("entry_orchestrator")


def _base_inputs(tenant_id: int, user_id: int, thread_id: str, inputs: dict) -> dict:
    out = dict(inputs or {})
    out.setdefault("tenant_id", tenant_id)
    out.setdefault("user_id", user_id)
    out.setdefault("session_id", thread_id)
    return out


async def route_and_run(
    *,
    text: str,
    tenant_id: int,
    user_id: int,
    thread_id: str,
    inputs: dict[str, Any] | None = None,
) -> dict:
    """入口编排：识别意图 → 选择流程 → 执行。"""
    decision = await classify_intent(text, tenant_id)
    flow = decision.get("flow")
    agents = decision.get("agents") or []
    orch = getattr(app_state, "orchestrator", None)

    if flow == "clarify" or not agents:
        return {
            "decision": decision,
            "need_input": ["请说明：规范问答 / 变更评审 / 发布验证"],
        }
    if flow == "branch":
        return {
            "decision": decision,
            "need_input": [f"请选择具体处理：{', '.join(agents)}"],
        }
    if orch is None:
        return {"decision": decision, "error": "编排器未就绪"}

    payload = _base_inputs(tenant_id, user_id, thread_id, inputs or {})

    # 单点流程：review/release 需要结构化输入，缺失则提示
    if flow == "single":
        agent = agents[0]
        if agent == "db_review" and not payload.get("sql_text"):
            return {"decision": decision, "need_input": ["请提供 sql_text/db_type/connection_id"]}
        if agent == "db_release" and not payload.get("request_id"):
            return {"decision": decision, "need_input": ["请提供 request_id/sandbox_connection_id"]}
        result = await orch.run_agent(agent, thread_id, payload)
        return {"decision": decision, "result": result}

    if flow == "sequential":
        # 含 HITL（评审审批/发布放行），不在入口一口气跑，统一走「变更编排」页逐阶段推进
        return {
            "decision": decision,
            "redirect": "/agent/db-workflow",
            "message": "评审→审批→沙箱验证→放行 请在「变更编排」页逐阶段推进",
        }

    if flow == "parallel":
        result = await orch.run_parallel(agents, thread_id, payload)
        return {"decision": decision, "result": result}

    return {"decision": decision, "need_input": ["暂不支持的流程"]}
