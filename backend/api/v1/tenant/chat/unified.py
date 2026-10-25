"""
unified_chat - 统一入口（设计文档 §7）

请求生命周期（SSE 流式）：
  会话归属校验 → 规则前置拦截(零 Token) → bert-chinese 意图粗分 → (模糊) LLM 路由
  → 权限点校验 → Orchestrator 分发 → SSE 事件流。
SSE 事件类型：routing_decision / progress / token / guidance / pipeline_plan / meta / done / error。
"""
from __future__ import annotations

import json
from typing import AsyncGenerator, Optional

from fastapi import APIRouter, Depends, Request
from sse_starlette.sse import EventSourceResponse

from backend.api.v1.tenant.chat.schemas import ChatIn
from backend.app_state import app_state
from backend.common.llm.llm_factory import LLMFactory
from backend.data.dao.agent.thread_dao import ThreadDao
from backend.middleware.auth import CurrentUser, get_current_user, tenant_of
from backend.security.rbac import Scope
from backend.security.security import check_input

router = APIRouter(prefix="/chat", tags=["chat"])


# 五类社交/元场景零 Token 前置拦截关键词
_PRE_RULES = {
    "greeting": ["你好", "hi", "hello"],
    "thanks": ["谢谢", "thanks"],
    "help": ["帮助", "怎么用"],
    "about": ["你是谁", "介绍下"],
    "fallback": ["？？？", "听不懂"],
}

# agent 类型 → 所需权限点：问哪一类就要求哪一类的 ask 权限
_SCOPE_BY_AGENT = {
    "qa": Scope.QA_ASK,
    "resume": Scope.RESUME_ASK,
    "exam": Scope.EXAM_ASK,
    "interview": Scope.INTERVIEW_ASK,
}


def _pre_intercept(text: str) -> Optional[str]:
    """规则前置拦截：命中即返回零 Token 回复，否则 None。"""
    low = text.strip().lower()
    for intent, words in _PRE_RULES.items():
        if any(w in low for w in words):
            return f"（{intent}）"
    return None


def _has_scope(scopes: list, required: Scope) -> bool:
    """是否具备该权限点（"*" 视为全量）。"""
    return "*" in scopes or required.value in scopes


async def _event(name: str, data: Dict) -> str:
    return json.dumps({"event": name, "data": data}, ensure_ascii=False)


async def _error_event(code: int, msg: str) -> str:
    return f"data: {await _event('error', {'code': code, 'msg': msg})}\n\n"


async def _chat_stream(
    request: Request, text: str, current: CurrentUser
) -> AsyncGenerator[str, None]:
    # get_current_user 已经保证租户可解析，tenant_of 负责把 Optional 收窄
    tenant_id = tenant_of(current)
    user_id = current.user_id

    # [0] 会话归属：客户端带来的 thread_id 必须属于当前用户，否则按不存在返回
    client_thread_id = request.headers.get("X-Thread-Id", "").strip()
    if client_thread_id and not await ThreadDao.is_owned(
        thread_id=client_thread_id, tenant_id=tenant_id, user_id=user_id
    ):
        yield await _error_event(404, "会话不存在")
        return

    # [1] 前置拦截（零 Token）
    pre = _pre_intercept(text)
    if pre is not None:
        yield f"data: {await _event('done', {'reply': pre})}\n\n"
        return

    # 输入护栏
    try:
        check_input(text)
    except Exception as exc:
        yield await _error_event(400, str(exc))
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

    # [3.5] 权限点：路由到哪个 agent 就要求对应 ask 权限，避免越权调用别的 agent
    required = _SCOPE_BY_AGENT.get(agent_type)
    if required is not None and not _has_scope(current.scopes, required):
        yield await _error_event(403, f"缺少权限 {required.value}")
        return

    # [4] 会话落库：没带 thread_id 就由服务端新建，不再落到共享的 "default" 上
    try:
        thread_id = client_thread_id or await ThreadDao.create(
            tenant_id=tenant_id, user_id=user_id, graph_name=agent_type
        )
    except Exception as exc:
        yield await _error_event(500, f"会话创建失败：{exc}")
        return
    yield f"data: {await _event('meta', {'thread_id': thread_id})}\n\n"

    # [5] Orchestrator 分发（单 Agent 直达）
    yield f"data: {await _event('progress', {'stage': 'dispatch'})}\n\n"
    try:
        result = await app_state.orchestrator.run_agent(  # type: ignore[union-attr]
            agent_type,
            thread_id,
            {"query": text, "tenant_id": tenant_id, "user_id": user_id},
        )
        yield f"data: {await _event('meta', {'result_keys': list(result.keys())})}\n\n"
    except Exception as exc:
        yield await _error_event(500, str(exc))
        return

    yield f"data: {await _event('done', {'reply': 'ok'})}\n\n"


@router.post("")
async def chat(
    request: Request, body: ChatIn, current: CurrentUser = Depends(get_current_user)
) -> EventSourceResponse:
    """统一入口：一句话 → 归属校验 → 拦截 → 路由 → Orchestrator → SSE 分发。"""
    text = body.text
    return EventSourceResponse(_chat_stream(request, text, current))
