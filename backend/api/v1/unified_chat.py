"""
unified_chat - 统一入口（设计文档 §7）

请求生命周期（SSE 流式）：
  规则前置拦截(零 Token) → bert-chinese 意图粗分 → (模糊) LLM 路由 → Orchestrator 分发 → SSE 事件流。
SSE 事件类型：routing_decision / progress / token / guidance / pipeline_plan / meta / done / error。
"""
from __future__ import annotations

import json
from typing import AsyncGenerator, Dict, Optional

from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse

from backend.app_state import app_state
from backend.core.llm_factory import LLMFactory
from backend.core.security import check_input

router = APIRouter(prefix="/v1", tags=["unified"])


# 五类社交/元场景零 Token 前置拦截关键词
_PRE_RULES = {
    "greeting": ["你好", "hi", "hello"],
    "thanks": ["谢谢", "thanks"],
    "help": ["帮助", "怎么用"],
    "about": ["你是谁", "介绍下"],
    "fallback": ["？？？", "听不懂"],
}


def _pre_intercept(text: str) -> Optional[str]:
    """规则前置拦截：命中即返回零 Token 回复，否则 None。"""
    low = text.strip().lower()
    for intent, words in _PRE_RULES.items():
        if any(w in low for w in words):
            return f"（{intent}）"
    return None


async def _event(name: str, data: Dict) -> str:
    return json.dumps({"event": name, "data": data}, ensure_ascii=False)


async def _chat_stream(request: Request, text: str) -> AsyncGenerator[str, None]:
    # [1] 前置拦截（零 Token）
    pre = _pre_intercept(text)
    if pre is not None:
        yield f"data: {await _event('done', {'reply': pre})}\n\n"
        return

    # 输入护栏
    try:
        check_input(text)
    except Exception as exc:
        yield f"data: {await _event('error', {'msg': str(exc)})}\n\n"
        return

    # [2] bert-chinese 意图粗分
    factory: LLMFactory = app_state.llm_factory  # type: ignore[assignment]
    intent = await factory.classify(text)

    # [3] 模糊意图交 LLM 路由（占位：DeepSeek 直接分类）
    confidence = 0.9 if intent != "general" else 0.3
    if intent == "general" and factory._llm is not None:
        # 占位 LLM 路由；真实实现见 M7
        intent = "qa"

    agent_type = intent if intent in ("resume", "qa", "exam", "interview") else "qa"
    yield f"data: {await _event('routing_decision', {'agent_type': agent_type, 'confidence': confidence})}\n\n"

    # [4] Orchestrator 分发（单 Agent 直达）
    yield f"data: {await _event('progress', {'stage': 'dispatch'})}\n\n"
    thread_id = request.headers.get("X-Thread-Id", "default")
    try:
        result = await app_state.orchestrator.run_agent(  # type: ignore[union-attr]
            agent_type, thread_id, {"query": text, "tenant_id": app_state.settings.app_name}
        )
        yield f"data: {await _event('meta', {'result_keys': list(result.keys())})}\n\n"
    except Exception as exc:
        yield f"data: {await _event('error', {'msg': str(exc)})}\n\n"
        return

    yield f"data: {await _event('done', {'reply': 'ok'})}\n\n"


@router.post("/chat")
async def chat(request: Request, body: Dict) -> EventSourceResponse:
    """统一入口：一句话 → 拦截 → 路由 → Orchestrator → SSE 分发。"""
    text = body.get("text", "")
    return EventSourceResponse(_chat_stream(request, text))
