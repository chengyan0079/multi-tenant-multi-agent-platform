"""智能问答接口：非流式 / SSE 流式问答，按租户隔离。"""

from __future__ import annotations

import json
import time
from typing import Any, List

import uuid6

from fastapi import APIRouter, Depends
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from backend.agents.qa.graph import build_qa_graph
from backend.app_state import app_state
from backend.common.logger import get_logger, trace_id_ctx
from backend.observability.tracing import tracing
from backend.common.llm.token_usage import TokenUsageCallback
from backend.data.dao.business.qa_result_dao import QaResultDao
from backend.data.sql.audit import audit_on_insert
from backend.common.response import success
from backend.middleware.auth import CurrentUser, get_current_user, tenant_of
from backend.security.rbac import Scope
from backend.security.security import require_scope
from backend.services.qa_chat_stop import (
    clear_chat_stop,
    is_chat_stopped,
    set_chat_stop,
)

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


async def _update_title_if_default(
    thread_id: str, tenant_id: int, user_id: int, question: str
) -> None:
    """首问后把会话标题从「新会话」更新为问题主题（仅默认标题生效），失败只告警。"""
    title = (question or "").strip()[:20]
    if not title:
        return
    try:
        from backend.data.dao.agent.thread_dao import ThreadDao

        await ThreadDao.update_title_if_default(
            thread_id=thread_id, tenant_id=tenant_id, user_id=user_id, title=title
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception(f"qa_session.title_update_failed | thread={thread_id} | {exc}")


def _contexts_from_state(state: Any) -> list[dict[str, Any]]:
    """从图状态 ranked_chunks 提取 RAGAS 用的检索上下文（父块正文优先）。"""
    chunks = (state or {}).get("ranked_chunks") or []
    out: list[dict[str, Any]] = []
    for chunk in chunks:
        if isinstance(chunk, dict):
            out.append(
                {
                    "doc_id": chunk.get("doc_id", ""),
                    "score": chunk.get("score", 0),
                    "source": chunk.get("source", ""),
                    "content": chunk.get("parent_content") or chunk.get("content", ""),
                }
            )
        else:
            out.append(
                {
                    "doc_id": getattr(chunk, "doc_id", ""),
                    "score": getattr(chunk, "score", 0),
                    "source": getattr(chunk, "source", ""),
                    "content": getattr(chunk, "parent_content", "")
                    or getattr(chunk, "content", ""),
                }
            )
    return out


NO_EXTERNAL_SOURCE = "模型内置知识（无外部引用）"


def _normalize_sources(sources: list[str], contexts: list[dict[str, Any]]) -> list[str]:
    """保证 sources 永远是可展示的非空字符串数组。"""
    out: list[str] = []
    for item in sources or []:
        text = str(item).strip()
        if text and text not in out:
            out.append(text)
        if len(out) >= 10:
            return out

    # 图没有回传来源时，用检索上下文兜底；标注为低相关候选，避免误当成已引用
    for context in contexts or []:
        source = str(context.get("source") or "").strip()
        if not source:
            continue
        label = f"低相关候选：{source}"
        if label not in out:
            out.append(label)
        if len(out) >= 10:
            break

    return out or [NO_EXTERNAL_SOURCE]


async def _persist_qa_result(
    *,
    tenant_id: int,
    user_id: int,
    session_id: str,
    thread_id: str,
    question: str,
    answer: str,
    answer_mode: str,
    query_type: str | None,
    confidence: float,
    sources: list[str],
    contexts: list[dict[str, Any]],
    enable_web_search: bool,
    latency_ms: int,
    token_usage: dict[str, Any] | None = None,
    state_values: dict[str, Any] | None = None,
    stream: bool = False,
    extra: dict[str, Any] | None = None,
) -> None:
    """问答结果落库；失败只告警，不影响问答返回。

    - sources：图/上下文兜底为非空字符串数组；
    - token_usage：由 TokenUsageCallback 汇总，一次图执行写一行；
    - extra：记录运行画像，便于排查低置信度、检索命中、Web 兜底和 usage 缺失。
    """
    state = state_values or {}
    usage = token_usage or {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "llm_calls": 0,
        "models": [],
        "usage_available": False,
        "errors": 0,
    }
    normalized_sources = _normalize_sources(sources, contexts)
    extra_data: dict[str, Any] = {
        "trace_id": trace_id_ctx.get(),
        "graph_name": "qa",
        "stream": stream,
        "answer_mode": answer_mode,
        "query_type": query_type,
        "confidence": float(confidence or 0),
        "fallback_used": bool(
            state.get("fallback_used", answer_mode in ("llm_direct", "web_augmented", "general"))
        ),
        "source_count": len(normalized_sources),
        "context_count": len(contexts or []),
        "ranked_chunk_count": len(state.get("ranked_chunks") or []),
        "web_search_result_count": len(state.get("web_search_results") or []),
        "enable_web_search": enable_web_search,
        "latency_ms": latency_ms,
        "token_usage": usage,
        "models": usage.get("models") or [],
        "usage_available": bool(usage.get("usage_available")),
    }
    if extra:
        extra_data.update(extra)

    try:
        await QaResultDao.insert(
            record={
                "id": str(uuid6.uuid7()),
                "trace_id": trace_id_ctx.get(),
                "tenant_id": tenant_id,
                "user_id": user_id,
                "session_id": session_id,
                "thread_id": thread_id,
                "agent_type": "qa",
                "question": question,
                "answer": answer,
                "answer_mode": answer_mode,
                "query_type": query_type,
                "confidence": float(confidence or 0),
                "retrieved_contexts": contexts,
                "sources": normalized_sources,
                "reference_answer": None,
                "latency_ms": latency_ms,
                "token_usage": usage,
                "enable_web_search": enable_web_search,
                # TODO(qa_result): 图异常/流式中断未写 failed 行，
                #  后续在异常分支补 status='failed' + error_msg。
                "status": "success",
                "error_msg": None,
                "extra": extra_data,
            },
            audit=audit_on_insert(tenant_id=tenant_id),
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception(f"qa_result.persist_failed | session={session_id} | {exc}")

    # 每条消息成功后刷新会话 updated_at，保证「会话列表」按最近活跃排序
    try:
        from backend.data.dao.agent.thread_dao import ThreadDao

        await ThreadDao.touch_qa_session(thread_id=thread_id, tenant_id=tenant_id, user_id=user_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception(f"qa_result.touch_failed | session={session_id} | {exc}")


# --------------------------------------------------------------------------- #
# 请求/响应模型
# --------------------------------------------------------------------------- #
class ChatRequest(BaseModel):
    session_id: str = Field(..., description="会话 ID，用于多轮上下文区分")
    message: str = Field(..., min_length=1, max_length=2000, description="用户提问内容")
    enable_web_search: bool = Field(False, description="低置信度时是否启用 Web 搜索补充")


class StopChatRequest(BaseModel):
    """停止某会话进行中的流式生成。"""

    session_id: str = Field(..., min_length=1, description="要停止的会话 ID")


# --------------------------------------------------------------------------- #
# 接口
# --------------------------------------------------------------------------- #
@router.post("/chat")
async def chat(
    req: ChatRequest,
    _: object = Depends(require_scope(Scope.QA_ASK)),  # noqa: B008
    current: CurrentUser = Depends(get_current_user),
) -> Any:
    """非流式智能问答：发送消息，返回完整回答。

    说明：解析会话线程、跑 QA 状态机，结果落库（RAGAS 样本源）；失败不阻断问答。
    请求：body { session_id: str, message: str, enable_web_search?: bool }
    权限：qa:ask
    返回：answer / answer_mode / confidence / sources / fallback_used
    """
    tenant_id = tenant_of(current)
    user_id = current.user_id
    thread_id = await _resolve_thread_id(tenant_id, user_id, req.session_id)
    # 首问后把会话标题从「新会话」更新为问题主题（仅默认标题生效）
    await _update_title_if_default(thread_id, tenant_id, user_id, req.message)

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
    usage_cb = TokenUsageCallback()
    config = {
        "configurable": {"thread_id": thread_id},
        "callbacks": [usage_cb],
    }

    started = time.perf_counter()
    try:
        result = await _get_graph().ainvoke(initial_state, config=tracing.with_callbacks(config))
    except Exception as e:  # noqa: BLE001 - 交由全局异常处理器统一包装
        logger.exception(f"chat.invoke_error | session={req.session_id} | {e}")
        raise
    latency_ms = int((time.perf_counter() - started) * 1000)

    contexts = _contexts_from_state(result)
    sources = _normalize_sources(result.get("sources", []), contexts)
    token_usage = usage_cb.as_dict()

    # 落库（RAGAS 样本源）；失败不阻断问答
    await _persist_qa_result(
        tenant_id=tenant_id,
        user_id=user_id,
        session_id=req.session_id,
        thread_id=thread_id,
        question=req.message,
        answer=result.get("answer", ""),
        answer_mode=result.get("answer_mode", "llm_direct"),
        query_type=result.get("query_type"),
        confidence=result.get("confidence", 0.0),
        sources=sources,
        contexts=contexts,
        enable_web_search=req.enable_web_search,
        latency_ms=latency_ms,
        token_usage=token_usage,
        state_values=result,
        stream=False,
    )

    return success(
        {
            "session_id": req.session_id,
            "answer": result.get("answer", ""),
            "answer_mode": result.get("answer_mode", "llm_direct"),
            "confidence": result.get("confidence", 0.0),
            "sources": sources,
            "fallback_used": result.get("fallback_used", False),
        }
    )


@router.post("/chat/stream")
async def chat_stream(
    req: ChatRequest,
    _: object = Depends(require_scope(Scope.QA_ASK)),  # noqa: B008
    current: CurrentUser = Depends(get_current_user),
) -> Any:
    """SSE 流式智能问答，逐 token 返回。

    说明：事件类型 progress / token / meta / stopped / done / error；支持服务端停止标记中断。
    请求：body { session_id: str, message: str, enable_web_search?: bool }
    权限：qa:ask
    返回：text/event-stream
    """
    tenant_id = tenant_of(current)
    user_id = current.user_id
    thread_id = await _resolve_thread_id(tenant_id, user_id, req.session_id)
    # 首问后把会话标题从「新会话」更新为问题主题（仅默认标题生效）
    await _update_title_if_default(thread_id, tenant_id, user_id, req.message)

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
    state_config = {"configurable": {"thread_id": thread_id}}
    usage_cb = TokenUsageCallback()
    config = {**state_config, "callbacks": [usage_cb]}

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
        started = time.perf_counter()
        answer_mode = "llm_direct"
        confidence = 0.0
        sources: List[str] = []
        answer_parts: List[str] = []
        stopped = False
        try:
            # 先发一帧，确保 SSE 响应头尽快建立（避免长耗时节点导致客户端/代理超时）
            yield {
                "data": json.dumps({"type": "progress", "stage": "准备中..."}, ensure_ascii=False)
            }
            # 进入前清掉可能残留的停止标记，避免误停本次生成
            await clear_chat_stop(tenant_id, user_id, req.session_id)
            async for event in _get_graph().astream_events(
                initial_state, config=config, version="v2"
            ):
                # 每个事件产出前检查停止标记（Redis，跨 worker 生效）
                if await is_chat_stopped(tenant_id, user_id, req.session_id):
                    stopped = True
                    break
                evt = event.get("event")
                node = event.get("metadata", {}).get("langgraph_node", "")

                # ① 节点开始 → 进度提示
                if evt == "on_chain_start" and node in _PROGRESS_LABELS:
                    yield {
                        "data": json.dumps(
                            {"type": "progress", "stage": _PROGRESS_LABELS[node]},
                            ensure_ascii=False,
                        )
                    }
                # ② LLM 流式 token（仅三个生成节点）
                elif evt == "on_chat_model_stream" and node in _GENERATE_NODES:
                    chunk = event.get("data", {}).get("chunk")
                    if chunk and chunk.content:
                        answer_parts.append(chunk.content)
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
            logger.exception(f"chat_stream.error | session={req.session_id} | {e}")
            yield {
                "data": json.dumps(
                    {"type": "error", "message": "流式输出异常，请使用普通接口重试"},
                    ensure_ascii=False,
                )
            }
            return
        finally:
            await clear_chat_stop(tenant_id, user_id, req.session_id)

        # 被用户停止：不落库（与 RAG-Ultra / rag-pro 一致），仅告知前端结束
        if stopped:
            yield {"data": json.dumps({"type": "stopped"}, ensure_ascii=False)}
            yield {"data": json.dumps({"type": "done"}, ensure_ascii=False)}
            return

        # ④ 落库（从图状态取检索上下文；失败不影响流式输出）
        latency_ms = int((time.perf_counter() - started) * 1000)
        try:
            snapshot = await _get_graph().aget_state(state_config)
            state_values = snapshot.values if snapshot and snapshot.values else {}
        except Exception as exc:  # noqa: BLE001
            logger.exception(f"chat_stream.state_error | session={req.session_id} | {exc}")
            state_values = {}

        contexts = _contexts_from_state(state_values)
        sources = _normalize_sources(sources or state_values.get("sources", []), contexts)
        token_usage = usage_cb.as_dict()

        await _persist_qa_result(
            tenant_id=tenant_id,
            user_id=user_id,
            session_id=req.session_id,
            thread_id=thread_id,
            question=req.message,
            answer="".join(answer_parts) or state_values.get("answer", ""),
            answer_mode=answer_mode,
            query_type=state_values.get("query_type"),
            confidence=confidence,
            sources=sources,
            contexts=contexts,
            enable_web_search=req.enable_web_search,
            latency_ms=latency_ms,
            token_usage=token_usage,
            state_values=state_values,
            stream=True,
        )

        # ⑤ 推送完整元数据帧
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
        # ⑥ 结束标志
        yield {"data": json.dumps({"type": "done"})}

    return EventSourceResponse(event_generator())


@router.post("/chat/stop", summary="停止当前会话的流式生成")
async def chat_stop(
    req: StopChatRequest,
    _: object = Depends(require_scope(Scope.QA_ASK)),  # noqa: B008
    current: CurrentUser = Depends(get_current_user),
) -> Any:
    """请求停止指定会话的流式生成。

    说明：写 Redis 停止标记，流式生成器在下一个事件前中断（跨 worker 生效）。
    请求：body { session_id: str 必填 }
    权限：qa:ask
    返回：{ session_id, stopped }
    """
    await set_chat_stop(tenant_of(current), current.user_id, req.session_id)
    return success({"session_id": req.session_id, "stopped": True})
