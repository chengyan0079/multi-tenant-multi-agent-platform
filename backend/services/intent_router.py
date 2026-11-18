"""入口意图识别 + 流程选择（A 单点 / B 串行 / C 并行 / D 条件）。

- ``classify_intent``：**纯规则**（无 LLM、确定性），供离线评测与编排入口复用。
- ``classify_as_intent``：适配统一入口 ``classify_fn`` 的桥接层，规则优先，
  规则无命中时按 ``INTENT_LLM_FALLBACK`` 开关可选 LLM 兜底；
  多 Agent 结论映射为保留标签 ``multi_agent`` + 编排 DSL 计划（不截断为单 Agent）。

输出 decision：{intent, agents, flow, confidence}
"""

from __future__ import annotations

import os

from backend.common.logger import get_logger

logger = get_logger("intent_router")

# 关键词 → agent（粗规则；DB 注册的 AgentSpec.intent_labels 可作为补充）
_KEYWORDS: dict[str, tuple[str, ...]] = {
    "db_review": ("评审", "审查", "风险", "ddl", "dml", "alter table", "drop table"),
    "db_release": ("沙箱", "影子", "发布验证", "执行验证", "发布上线"),
    "qa": ("规范", "最佳实践", "事故", "知识", "为什么", "怎么做", "如何"),
}

# 组合 → 流程
_SEQUENTIAL = [({"db_review", "db_release"}, "change_governance")]
_PARALLEL = [
    ({"db_review", "qa"}, "review_with_knowledge"),
    ({"db_release", "qa"}, "release_with_knowledge"),
]


def _rule_agents(text: str) -> list[str]:
    low = (text or "").lower()
    hit: list[str] = []
    for agent, kws in _KEYWORDS.items():
        if any(k.lower() in low for k in kws):
            hit.append(agent)
    return hit


async def _llm_agents(text: str) -> list[str]:
    """规则无命中时用 LLM 兜底（失败返回空，不阻断）。"""
    try:
        from backend.common.llm.llm_factory import get_llm

        llm = await get_llm("qa")
        prompt = (
            "判断用户意图属于哪类，只输出一个词：qa(规范/知识问答)、"
            "db_review(数据库变更评审)、db_release(发布/沙箱验证)、unknown。\n"
            f"用户：{text}"
        )
        raw = await llm.ainvoke(prompt)
        label = str(getattr(raw, "content", raw)).strip().lower()
        if label in _KEYWORDS:
            return [label]
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"intent LLM 兜底失败: {type(exc).__name__}: {exc}")
    return []


def _llm_fallback_enabled() -> bool:
    """规则无命中时是否启用 LLM 兜底（默认开；INTENT_LLM_FALLBACK=0 关闭）。"""
    return os.getenv("INTENT_LLM_FALLBACK", "1").strip().lower() not in {
        "0",
        "false",
        "off",
        "no",
    }


def plan_from_decision(decision: dict) -> dict:
    """把 flow 决策翻译成编排 DSL（步骤结构见 orchestrator.run_plan）。

    统一编排层以 ``plan["steps"]`` 判空，故并行也包一层 sequence；
    并行分支在 DSL 里是 ``{"type": "parallel", "agents": [...]}``。
    """
    agents = list(decision.get("agents") or [])
    if decision.get("flow") == "parallel":
        return {"type": "sequence", "steps": [{"type": "parallel", "agents": agents}]}
    return {"type": "sequence", "steps": [{"type": "agent", "agent": a} for a in agents]}


def decide_flow(agents: list[str]) -> dict:
    """按命中的 agent 集合选择流程 A/B/C/D。"""
    s = set(agents)
    if not s:
        return {"intent": "unknown", "agents": [], "flow": "clarify", "confidence": 0.0}
    for combo, intent in _SEQUENTIAL:
        if combo <= s:
            # 顺序取命中集合的原始次序（_KEYWORDS 声明序），不硬编码具体 Agent，
            # 否则新增组合会带上不属于自己的前置步骤。
            ordered = [a for a in agents if a in combo] + [a for a in agents if a not in combo]
            return {
                "intent": intent,
                "agents": ordered,
                "flow": "sequential",
                "confidence": 0.85,
            }
    for combo, intent in _PARALLEL:
        if combo <= s:
            ordered = [a for a in agents if a in combo] + [a for a in agents if a not in combo]
            return {
                "intent": intent,
                "agents": ordered,
                "flow": "parallel",
                "confidence": 0.75,
            }
    if len(s) == 1:
        return {"intent": agents[0], "agents": agents, "flow": "single", "confidence": 0.9}
    return {"intent": "multi", "agents": agents, "flow": "branch", "confidence": 0.6}


async def classify_as_intent(system_prompt: str, user_input: str):
    """适配 UnifiedRouter 的 classify_fn 签名（返回 IntentResponse）。

    规则优先（快、确定、省 token）；规则无命中时才按开关问一次 LLM。
    - 单一 Agent → 直接给出该 label，走单 Agent 分发；
    - 多 Agent   → 返回保留标签 ``multi_agent`` 并附编排 DSL，由编排层以
      pipeline 模式跑完整链路（此前截断为 ``agents[0]``，组合诉求会被静默丢弃）；
    - 仍无结论 → ``clarify`` 追问。
    """
    from backend.orchestration.unified_intent import IntentResponse

    text = (user_input or "").strip()
    decision = await classify_intent(text)
    source = "rule"

    if not (decision.get("agents") or []) and text and _llm_fallback_enabled():
        llm_agents = await _llm_agents(text)
        if llm_agents:
            decision = decide_flow(llm_agents)
            source = "llm"
            logger.info(f"intent.llm_fallback | text={text[:40]} | {decision}")

    agents = decision.get("agents") or []
    reason = f"{decision.get('intent', 'unknown')}（{decision.get('flow', '')}/{source}）"
    if not agents:
        return IntentResponse(label="clarify", confidence=0.0, reason=reason)
    confidence = float(decision.get("confidence") or 0.0)
    if len(agents) > 1:
        return IntentResponse(
            label="multi_agent",
            confidence=confidence,
            reason=reason,
            plan=plan_from_decision(decision),
        )
    return IntentResponse(label=agents[0], confidence=confidence, reason=reason)


async def classify_intent(text: str, tenant_id: int | None = None) -> dict:
    """意图识别：**固定规则**（无 LLM，确定性），仅 5 种映射：

    1. 规范/知识问答       → single qa
    2. 评审 SQL（带 entry）→ single db_review
    3. 规范 + 评审         → parallel qa+db_review
    4. 评审后发布验证      → sequential（编排层按 pipeline 模式执行）
    5. 无法识别            → clarify
    """
    agents = _rule_agents(text)
    decision = decide_flow(agents)
    logger.info(f"intent.decision | text={text[:40]} | {decision}")
    return decision
