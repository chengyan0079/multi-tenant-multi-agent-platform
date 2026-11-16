"""入口意图识别 + 流程选择（A 单点 / B 串行 / C 并行 / D 条件）。

规则优先（快、确定），LLM 仅在规则无命中时兜底（可配）。
输出 decision：{intent, agents, flow, confidence, reason}
"""

from __future__ import annotations

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
        logger.warning(f"intent LLM 兜底失败: {exc}")
    return []


def decide_flow(agents: list[str]) -> dict:
    """按命中的 agent 集合选择流程 A/B/C/D。"""
    s = set(agents)
    if not s:
        return {"intent": "unknown", "agents": [], "flow": "clarify", "confidence": 0.0}
    for combo, intent in _SEQUENTIAL:
        if combo <= s:
            ordered = ["db_review", "db_release"] + [a for a in agents if a not in combo]
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

    规则优先（快、确定、省 token）；映射为单 agent label，clarify 兜底。
    多 Agent 流程（B 串行 / C 并行）由 /entry-orchestrate 独立处理。
    """
    from backend.orchestration.unified_intent import IntentResponse

    decision = await classify_intent(user_input or "")
    agents = decision.get("agents") or []
    if not agents:
        return IntentResponse(
            label="clarify", confidence=0.0, reason=decision.get("intent", "unknown")
        )
    return IntentResponse(
        label=agents[0],
        confidence=float(decision.get("confidence") or 0.0),
        reason=str(decision.get("intent") or ""),
    )


async def classify_intent(text: str, tenant_id: int | None = None) -> dict:
    """意图识别：**固定规则**（无 LLM，确定性），仅 5 种映射：

    1. 规范/知识问答       → single qa
    2. 评审 SQL（带 entry）→ single db_review
    3. 规范 + 评审         → parallel qa+db_review
    4. 评审后发布验证      → sequential（走变更编排页）
    5. 无法识别            → clarify
    """
    agents = _rule_agents(text)
    decision = decide_flow(agents)
    logger.info(f"intent.decision | text={text[:40]} | {decision}")
    return decision
