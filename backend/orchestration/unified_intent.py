"""双通道路由（D13）：显式通道跳过分类；隐式通道规则前置 + LLM 结构化分类。

纯逻辑、可注入分类函数，便于 DB-free 单测；真实 LLM 分类走 get_structured_llm 默认实现（Step 7 接线）。
规则前置命中（问候/感谢/道别/身份/能力）直接模板回复、零 Token（§4.3）。
"""
from __future__ import annotations

from typing import Awaitable, Callable, Optional

from backend.orchestration.agent_registry import AgentRegistry
from backend.orchestration.unified_schemas import (
    InitValuesPayload,
    IntentResponse,
    RoutingDecision,
)
from backend.prompts import unified as prompts

# 内建保留 label（§3.3）：不对应具体 Agent，由编排层直接映射执行模式
_RESERVED_LABELS = frozenset({"clarify", "multi_agent"})

# 规则前置：5 类关键词（§4.3），小写子串匹配
_RULE_GREETING = ("你好", "您好", "hi", "hello", "在吗", "在么")
_RULE_THANKS = ("谢谢", "感谢", "多谢", "thx", "辛苦了")
_RULE_BYE = ("再见", "拜拜", "下次", "88", "回见")
_RULE_IDENTITY = ("你是谁", "你是什么", "你叫什么", "介绍下你", "介绍你")
_RULE_CAPABILITY = ("你能做", "你会什么", "你能帮", "有什么功能", "有哪些能力", "能干什么")


def classify_rule(message: str) -> Optional[str]:
    """返回命中的规则类型；未命中返回 None。"""
    m = message.strip().lower()
    if any(k in m for k in _RULE_GREETING):
        return "greeting"
    if any(k in m for k in _RULE_THANKS):
        return "thanks"
    if any(k in m for k in _RULE_BYE):
        return "bye"
    if any(k in m for k in _RULE_IDENTITY):
        return "identity"
    if any(k in m for k in _RULE_CAPABILITY):
        return "capability"
    return None


async def _default_classify(system_prompt: str, user_input: str) -> IntentResponse:
    """真实 LLM 结构化分类（默认实现，Step 7 接线；单测用 classify_fn 注入替换）。"""
    from langchain_core.messages import HumanMessage, SystemMessage

    from backend.llm.llm_factory import get_structured_llm

    llm = await get_structured_llm("unified", IntentResponse)
    resp = await llm.ainvoke(
        [SystemMessage(content=system_prompt), HumanMessage(content=user_input)]
    )
    if isinstance(resp, IntentResponse):
        return resp
    return IntentResponse.model_validate(resp)


class UnifiedRouter:
    """双通道路由器：消费 AgentRegistry 的 spec / 派生映射，不持有业务状态。"""

    def __init__(self, registry: AgentRegistry) -> None:
        self._registry = registry

    async def route(
        self,
        *,
        message: str,
        explicit_agent_type: Optional[str] = None,
        history: str = "",
        classify_fn: Optional[
            Callable[[str, str], Awaitable[IntentResponse]]
        ] = None,
        default_agent_type: Optional[str] = None,
        tenant_id: Optional[int] = None,
    ) -> RoutingDecision:
        # 通道 A：显式（卡片 / 模板问题）→ 跳过意图分类
        if explicit_agent_type:
            spec = self._spec_for(explicit_agent_type)
            if spec is not None:
                return RoutingDecision(
                    label=explicit_agent_type,
                    agent_type=explicit_agent_type,
                    source="explicit",
                    confidence=1.0,
                    execution_mode=spec.execution_mode,
                    spec_version=spec.version or "",
                    init_values=InitValuesPayload(),
                )
            # 已注册但被停用（全局或租户维度）→ 明确拒绝，不静默兜底
            if self._registry.is_registered(explicit_agent_type) and not (
                self._registry.is_enabled_for_tenant(explicit_agent_type, tenant_id)
            ):
                return RoutingDecision(
                    label=explicit_agent_type,
                    agent_type=explicit_agent_type,
                    source="explicit",
                    confidence=1.0,
                    execution_mode="stream",
                    error_code="FORBIDDEN",
                    init_values=InitValuesPayload(),
                )
            # 完全未知的类型 → 走默认兜底（不中断）

        # 通道 B-1：规则前置
        rule = classify_rule(message)
        if rule is not None:
            return RoutingDecision(
                label=rule,
                agent_type="",
                source="rule",
                confidence=1.0,
                execution_mode="rule",
                init_values=InitValuesPayload(),
            )

        # 通道 B-2：LLM 结构化分类
        try:
            fn = classify_fn or _default_classify
            system_prompt = self._registry.render_route_prompt()
            user_input = self._registry.render_turn_input(history, message)
            intent: IntentResponse = await fn(system_prompt, user_input)
            # 内建保留 label：clarify → 追问；multi_agent → 串联（§3.3）
            if intent.label in _RESERVED_LABELS:
                exec_mode = "clarify" if intent.label == "clarify" else "pipeline"
                return RoutingDecision(
                    label=intent.label,
                    agent_type=intent.label,
                    source="llm",
                    confidence=intent.confidence,
                    reason=intent.reason,
                    execution_mode=exec_mode,
                    init_values=intent.init_values,
                )
            agent_type = self._registry.label_to_agent(intent.label)
            if agent_type is None:
                default = default_agent_type or self._default_agent_type()
                return self._fallback(default, f"未知 label={intent.label!r}，回退默认")
            spec = self._spec_for(agent_type)
            return RoutingDecision(
                label=intent.label,
                agent_type=agent_type,
                source="llm",
                confidence=intent.confidence,
                reason=intent.reason,
                execution_mode=spec.execution_mode if spec else "stream",
                spec_version=spec.version or "" if spec else "",
                init_values=intent.init_values,
            )
        except Exception:
            default = default_agent_type or self._default_agent_type()
            return self._fallback(default, "分类异常，使用默认 Agent")

    def rule_reply(self, rule: str, specs: Optional[list] = None) -> str:
        """按规则类型返回模板回复（capability 由 specs 动态拼装）。"""
        if rule == "greeting":
            return prompts.RULE_REPLY_GREETING
        if rule == "thanks":
            return prompts.RULE_REPLY_THANKS
        if rule == "bye":
            return prompts.RULE_REPLY_BYE
        if rule == "identity":
            return prompts.RULE_REPLY_IDENTITY
        if rule == "capability":
            items = "\n".join(
                prompts.DYNAMIC_CAPABILITY_ITEM.format(
                    display_name=s.display_name,
                    description=s.description,
                    example=s.intent_examples[0] if s.intent_examples else "",
                )
                for s in (specs or self._registry.specs())
            )
            return prompts.RULE_REPLY_CAPABILITY.format(capabilities=items)
        return ""

    # ------------------------------------------------------------------ #
    def _spec_for(self, agent_type: str):
        for s in self._registry.specs():
            if s.agent_type == agent_type:
                return s
        return None

    def _default_agent_type(self) -> str:
        for s in self._registry.specs():
            if s.default_agent:
                return s.agent_type
        specs = self._registry.specs()
        return specs[0].agent_type if specs else ""

    def _fallback(self, agent_type: str, reason: str) -> RoutingDecision:
        spec = self._spec_for(agent_type)
        return RoutingDecision(
            label=agent_type,
            agent_type=agent_type,
            source="fallback",
            confidence=0.0,
            reason=reason,
            fallback_used=True,
            execution_mode=spec.execution_mode if spec else "stream",
            spec_version=spec.version or "" if spec else "",
            init_values=InitValuesPayload(),
        )
