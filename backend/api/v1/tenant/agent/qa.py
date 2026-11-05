"""智能问答直连接口（standalone，挂在 /api/v1/tenant/qa）。

提供三类接口，对齐参考项目 backend/api/v1/qa.py 的形态：
- POST /chat         非流式问答，统一信封 success() 返回
- POST /chat/stream  SSE 流式问答（token 逐字推送）
- GET  /sessions/{id}/history  会话历史与摘要

鉴权与本项目一致：require_scope(Scope.QA_ASK) + get_current_user；数据按租户隔离。
SSE 事件格式（data 内 JSON）：progress / token / meta / done / error。
"""
from __future__ import annotations

import json
from typing import Any, List, Optional

from fastapi import APIRouter, Depends
from langchain_core.messages import AIMessage, HumanMessage
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from backend.agents.qa.graph import build_qa_graph
from backend.app_state import app_state
from backend.common.logger import get_logger
from backend.common.response import success
from backend.middleware.auth import CurrentUser, get_current_user, tenant_of
from backend.security.rbac import Scope
from backend.security.security import require_scope

logger = get_logger("qa_api")

router = APIRouter(prefix="/qa", tags=["qa"])

# 懒加载图：确保 app_state.checkpointer（启动期注入）就绪后再编译
_graph = None


def _get_graph():
    global _graph
    if _graph is None:
        _graph = build_qa_graph()
    return _graph


async def _resolve_thread_id(tenant_id: int, user_id: int, session_id: str) -> str:
    """按 (租户, 用户, 会话) find-or-create agent_thread，返回其 UUID 作为 LangGraph thread_id。

    与 chat 路径一致：thread_id 即 agent_thread.id，可经 agent_thread 按 tenant_id 统计/查询；
    session_key 拼入查找键，确保同一用户不同会话落到不同线程，且 tenant 维度参与隔离。
    """
    from backend.data.dao.agent.thread_dao import ThreadDao

    return await ThreadDao.get_or_create(
        tenant_id=tenant_id, user_id=user_id, graph_name="qa", session_key=session_id
    )


# --------------------------------------------------------------------------- #
# 请求/响应模型
# --------------------------------------------------------------------------- #
class ChatRequest(BaseModel):
    session_id: str = Field(..., description="会话 ID，用于多轮上下文区分")
    message: str = Field(..., min_length=1, max_length=2000, description="用户提问内容")
    enable_web_search: bool = Field(False, description="低置信度时是否启用 Web 搜索补充")


class SessionMessage(BaseModel):
    role: str
    content: str


# --------------------------------------------------------------------------- #
# 接口
# --------------------------------------------------------------------------- #
@router.post("/chat")
async def chat(
    req: ChatRequest,
    _: object = Depends(require_scope(Scope.QA_ASK)),  # noqa: B008
    current: CurrentUser = Depends(get_current_user),
) -> Any:
    """智能问答（非流式）：发送用户消息，等待完整回答后返回。"""
    tenant_id = tenant_of(current)
    user_id = current.user_id
    thread_id = await _resolve_thread_id(tenant_id, user_id, req.session_id)

    initial_state = {
        "messages": [HumanMessage(content=req.message)],
        "query": req.message,
        "user_id": user_id,
        "tenant_id": tenant_id,
        "session_id": req.session_id,
        "query_type": "PRECISE",  # 占位，classify_query_node 会重新判定并覆盖
        "enable_web_search": req.enable_web_search,
        "web_search_results": [],  # 每轮重置，防止上轮搜索结果污染本轮 sources
    }
    config = {"configurable": {"thread_id": thread_id}}

    try:
        result = await _get_graph().ainvoke(initial_state, config=config)
    except Exception as e:  # noqa: BLE001 - 交由全局异常处理器统一包装
        logger.error(f"chat.invoke_error | session={req.session_id} | {e}", exc_info=True)
        raise

    return success({
        "session_id": req.session_id,
        "answer": result.get("answer", ""),
        "answer_mode": result.get("answer_mode", "llm_direct"),
        "confidence": result.get("confidence", 0.0),
        "sources": result.get("sources", []),
        "fallback_used": result.get("fallback_used", False),
    })


@router.post("/chat/stream")
async def chat_stream(
    req: ChatRequest,
    _: object = Depends(require_scope(Scope.QA_ASK)),  # noqa: B008
    current: CurrentUser = Depends(get_current_user),
) -> Any:
    """流式智能问答（SSE）：与 /chat 相同入参，但以 Server-Sent Events 流式返回。

    事件类型：progress（节点进度）/ token（LLM 逐字）/ meta（结束元数据）/ done（结束）/ error（异常）。
    """
    tenant_id = tenant_of(current)
    user_id = current.user_id
    thread_id = await _resolve_thread_id(tenant_id, user_id, req.session_id)

    initial_state = {
        "messages": [HumanMessage(content=req.message)],
        "query": req.message,
        "user_id": user_id,
        "tenant_id": tenant_id,
        "session_id": req.session_id,
        "query_type": "PRECISE",
        "enable_web_search": req.enable_web_search,
        "web_search_results": [],
    }
    config = {"configurable": {"thread_id": thread_id}}

    # 仅对这些生成节点产生的 LLM token 做流式输出
    _GENERATE_NODES = {"generate_rag", "generate_direct", "generate_general"}
    # 节点开始时的友好进度标签
    _PROGRESS_LABELS = {
        "classify_query": "理解问题中...",
        "hyde_generate": "理解问题中...",
        "multi_query_rewrite": "改写查询中...",
        "retrieve": "检索相关知识...",
        "web_search": "检索互联网...",
        "generate_general": "思考中...",
    }

    async def event_generator():
        answer_mode = "llm_direct"
        confidence = 0.0
        sources: List[str] = []
        try:
            async for event in _get_graph().astream_events(initial_state, config=config, version="v2"):
                evt = event.get("event")
                node = event.get("metadata", {}).get("langgraph_node", "")

                # ① 节点开始 → 进度提示
                if evt == "on_chain_start" and node in _PROGRESS_LABELS:
                    yield {
                        "data": json.dumps(
                            {"type": "progress", "stage": _PROGRESS_LABELS[node]}, ensure_ascii=False
                        )
                    }
                # ② LLM 流式 token（仅三个生成节点）
                elif evt == "on_chat_model_stream" and node in _GENERATE_NODES:
                    chunk = event.get("data", {}).get("chunk")
                    if chunk and chunk.content:
                        yield {
                            "data": json.dumps(
                                {"type": "token", "content": chunk.content}, ensure_ascii=False
                            )
                        }
                # ③ 生成节点结束 → 捕获元数据（模式 / 来源 / 置信度）
                elif evt == "on_chain_end" and node in _GENERATE_NODES:
                    output = event.get("data", {}).get("output", {})
                    if isinstance(output, dict):
                        if output.get("answer_mode"):
                            answer_mode = output["answer_mode"]
                        if output.get("sources") is not None:
                            sources = output["sources"]
                        conf = (output.get("structured_output") or {}).get("confidence")
                        if conf is not None:
                            confidence = conf
        except Exception as e:  # noqa: BLE001
            logger.error(f"chat_stream.error | session={req.session_id} | {e}", exc_info=True)
            yield {
                "data": json.dumps(
                    {"type": "error", "message": "流式输出异常，请使用普通接口重试"}, ensure_ascii=False
                )
            }
            return

        # ④ 推送完整元数据帧
        yield {
            "data": json.dumps(
                {
                    "type": "meta",
                    "session_id": req.session_id,
                    "answer_mode": answer_mode,
                    "confidence": confidence,
                    "sources": sources,
                },
                ensure_ascii=False,
            )
        }
        # ⑤ 结束标志
        yield {"data": json.dumps({"type": "done"})}

    return EventSourceResponse(event_generator())


@router.get("/sessions/{session_id}/history")
async def get_session_history(
    session_id: str,
    _: object = Depends(require_scope(Scope.QA_ASK)),  # noqa: B008
    current: CurrentUser = Depends(get_current_user),
) -> Any:
    """获取指定会话的历史消息与摘要。

    数据来源：
      - 摘要（summary）：从 checkpointer 持久化的 state.existing_summary 读取（由 save_memory_node 写回）。
      - 完整消息列表：从 LangGraph checkpointer 读取该 thread_id 的 messages 字段。
    读取失败仅告警，不影响其他字段返回。
    """
    tenant_id = tenant_of(current)
    user_id = current.user_id
    thread_id = await _resolve_thread_id(tenant_id, user_id, session_id)

    summary: Optional[str] = None
    messages: List[SessionMessage] = []
    total_turns = 0
    try:
        state_snap = await _get_graph().aget_state({"configurable": {"thread_id": thread_id}})
        if state_snap and state_snap.values:
            values = state_snap.values
            summary = values.get("existing_summary")
            for msg in values.get("messages", []):
                content = msg.text if hasattr(msg, "text") and not callable(msg.text) else str(msg.content)
                if isinstance(msg, HumanMessage):
                    messages.append(SessionMessage(role="user", content=content))
                elif isinstance(msg, AIMessage):
                    messages.append(SessionMessage(role="assistant", content=content))
            total_turns = sum(1 for m in messages if m.role == "user")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"history.checkpoint_error | session={session_id} | {e}")

    return success({
        "session_id": session_id,
        "messages": [m.model_dump() for m in messages],
        "summary": summary,
        "total_turns": total_turns,
    })
