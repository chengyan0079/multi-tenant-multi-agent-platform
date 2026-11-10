"""模拟面试接口（租户端）。"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import uuid6
from fastapi import APIRouter, Depends, HTTPException, Query, status
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from pydantic import BaseModel, Field
from sqlalchemy import text
from sse_starlette.sse import EventSourceResponse

from backend.agents.interview.graph import build_interview_graph
from backend.app_state import app_state
from backend.common.logger import get_logger
from backend.observability.tracing import tracing
from backend.common.response import success
from backend.data.dao.agent.thread_dao import ThreadDao
from backend.data.sql import fetch_one, fetch_page, session_scope
from backend.middleware.auth import CurrentUser, get_current_user, tenant_of
from backend.security.rbac import Scope
from backend.security.security import require_scope
from backend.services.interview_chat_stop import (
    clear_interview_stop,
    is_interview_stopped,
    set_interview_stop,
)

logger = get_logger("interview_api")

router = APIRouter(prefix="/interview", tags=["interview"])

# 懒加载：确保启动期 app_state.checkpointer 已注入后再编译
_graph = None


def _get_graph():
    global _graph
    if app_state.checkpointer is None:
        raise HTTPException(status_code=503, detail="checkpointer 未就绪")
    if _graph is None:
        _graph = build_interview_graph()
    return _graph


class StartSessionRequest(BaseModel):
    target_position: str = Field(..., min_length=1, max_length=128)
    resume_review_id: str | None = Field(None, description="可选，关联简历评审")


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=8000)


class StopChatRequest(BaseModel):
    session_id: str = Field(..., min_length=1, description="要停止的面试会话 ID")


def _identity(current: CurrentUser) -> tuple[int, int]:
    return tenant_of(current), current.user_id


def _uuid_or_400(value: str, field: str) -> str:
    try:
        return str(UUID(value))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"{field} 不是合法 UUID") from exc


def _message_text(value: str) -> str:
    text = value.strip()
    if not text:
        raise HTTPException(status_code=400, detail="message 不能为空")
    return text


def _msg_text(message: BaseMessage) -> str:
    content = message.content
    if isinstance(content, list):
        return "".join(
            part.get("text", "") if isinstance(part, dict) else str(part) for part in content
        )
    return str(content)


def _last_ai_text(messages: list[BaseMessage]) -> str:
    for message in reversed(messages):
        if isinstance(message, AIMessage):
            return _msg_text(message)
    return ""


def _iso(value: Any) -> str | None:
    return value.isoformat() if value else None


def _session_item(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "session_id": row["session_id"],
        "thread_id": str(row["thread_id"]),
        "target_position": row["target_position"],
        "status": row["status"],
        "overall_score": row.get("overall_score"),
        "finished_at": _iso(row.get("finished_at")),
        "created_at": _iso(row.get("create_at")),
    }


async def _load_session(session_id: str, tenant_id: int, user_id: int) -> dict[str, Any] | None:
    async with session_scope() as session:
        return await fetch_one(
            session,
            text(
                """
                SELECT session_id, thread_id, target_position, status,
                       overall_score, report, finished_at, create_at
                FROM agent_interview_sessions
                WHERE session_id = :session_id
                  AND tenant_id = :tenant_id
                  AND user_id = :user_id
                  AND status <> 'deleted'
                """
            ),
            {
                "session_id": session_id,
                "tenant_id": tenant_id,
                "user_id": user_id,
            },
        )


def _config(thread_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": thread_id}}


async def _history_messages(thread_id: str) -> list[dict[str, str]]:
    """从 LangGraph checkpointer 的最新快照回放 Human/AI 消息。"""
    messages: list[dict[str, str]] = []
    try:
        snapshot = await _get_graph().aget_state(_config(thread_id))
        values = snapshot.values if snapshot and snapshot.values else {}
        for message in values.get("messages", []):
            content = _msg_text(message)
            if not content.strip():
                continue
            if isinstance(message, HumanMessage):
                # 创建会话时注入的内部哨兵，不展示给学员
                if content.strip() == "[开始面试]":
                    continue
                messages.append({"role": "user", "content": content})
            elif isinstance(message, AIMessage):
                messages.append({"role": "assistant", "content": content})
    except Exception as exc:  # noqa: BLE001 - 历史读取失败不影响会话信息
        logger.exception(f"interview.history_failed | thread={thread_id} | {exc}")
    return messages


async def _archive_session(*, session_id: str, thread_id: str, tenant_id: int, user_id: int) -> int:
    """软删：业务表标记 deleted，agent_thread 归档；checkpointer 保留可恢复。"""
    params = {
        "session_id": session_id,
        "thread_id": thread_id,
        "tenant_id": tenant_id,
        "user_id": user_id,
    }
    async with session_scope() as session:
        result = await session.execute(
            text(
                """
                UPDATE agent_interview_sessions
                   SET status = 'deleted', updated_at = now()
                 WHERE session_id = :session_id
                   AND tenant_id = :tenant_id
                   AND user_id = :user_id
                   AND status <> 'deleted'
                """
            ),
            params,
        )
        affected = int(result.rowcount or 0)
        if affected:
            await session.execute(
                text(
                    """
                    UPDATE agent_thread
                       SET status = 'archived', updated_at = now()
                     WHERE id = CAST(:thread_id AS uuid)
                       AND tenant_id = :tenant_id
                       AND user_id = :user_id
                       AND graph_name = 'interview'
                       AND session_key = :session_id
                    """
                ),
                params,
            )
        return affected


async def _create_session(
    *,
    tenant_id: int,
    user_id: int,
    session_id: str,
    thread_id: str,
    target_position: str,
    resume_review_id: str | None,
) -> None:
    async with session_scope() as session:
        await session.execute(
            text(
                """
                INSERT INTO agent_interview_sessions
                    (id, tenant_id, user_id, session_id, thread_id,
                     target_position, resume_review_id, summary, report,
                     overall_score, status, create_user_id, update_user_id,
                     create_tenant_id, update_tenant_id)
                VALUES
                    (CAST(:id AS uuid), :tenant_id, :user_id, :session_id,
                     CAST(:thread_id AS uuid), :target_position,
                     CAST(:resume_review_id AS uuid), '', '{}'::json,
                     0, 'in_progress', :user_id, :user_id, :tenant_id, :tenant_id)
                """
            ),
            {
                "id": str(uuid6.uuid7()),
                "tenant_id": tenant_id,
                "user_id": user_id,
                "session_id": session_id,
                "thread_id": thread_id,
                "target_position": target_position,
                "resume_review_id": resume_review_id,
            },
        )


async def _mark_session_failed(session_id: str, tenant_id: int, user_id: int) -> None:
    """建会话后图执行失败时，避免留下永久 in_progress。"""
    try:
        async with session_scope() as session:
            await session.execute(
                text(
                    "UPDATE agent_interview_sessions SET status = 'failed' "
                    "WHERE session_id = :session_id AND tenant_id = :tenant_id "
                    "AND user_id = :user_id AND status <> 'deleted'"
                ),
                {
                    "session_id": session_id,
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                },
            )
    except Exception as exc:  # noqa: BLE001
        logger.exception(f"interview.mark_failed_error | {exc}")


@router.post("/sessions", status_code=status.HTTP_201_CREATED)
async def start_session(
    req: StartSessionRequest,
    _: object = Depends(require_scope(Scope.INTERVIEW_ASK)),  # noqa: B008
    current: CurrentUser = Depends(get_current_user),
) -> Any:
    """创建面试会话并生成开场白。

    说明：按目标岗位初始化多阶段面试状态机，注入开场白后返回首轮提问。
    请求：body { target_position: str 必填, resume_review_id: str? 可选(关联简历评审) }
    权限：interview:ask
    返回：session_id / thread_id / target_position / status / current_stage / message(开场白)
    """
    tenant_id, user_id = _identity(current)
    target_position = req.target_position.strip()
    if not target_position:
        raise HTTPException(status_code=400, detail="target_position 不能为空")

    resume_review_id = (
        _uuid_or_400(req.resume_review_id, "resume_review_id") if req.resume_review_id else None
    )
    if resume_review_id:
        async with session_scope() as session:
            resume = await fetch_one(
                session,
                text(
                    "SELECT 1 AS ok FROM agent_resume_reviews "
                    "WHERE id = CAST(:id AS uuid) AND tenant_id = :tenant_id"
                ),
                {"id": resume_review_id, "tenant_id": tenant_id},
            )
        if not resume:
            raise HTTPException(status_code=400, detail="简历评审不存在或不属于本租户")

    session_id = str(uuid6.uuid7())
    thread_id = await ThreadDao.get_or_create(
        tenant_id=tenant_id,
        user_id=user_id,
        graph_name="interview",
        session_key=session_id,
    )
    await _create_session(
        tenant_id=tenant_id,
        user_id=user_id,
        session_id=session_id,
        thread_id=thread_id,
        target_position=target_position,
        resume_review_id=resume_review_id,
    )

    initial_state = {
        "messages": [HumanMessage(content="[开始面试]")],
        "user_id": user_id,
        "tenant_id": tenant_id,
        "thread_id": thread_id,
        "session_id": session_id,
        "target_position": target_position,
        "resume_review_id": resume_review_id,
        "resume_projects": [],
        "resume_skills": [],
        "current_stage": "warmup",
        "stage_turn_count": 0,
        "total_turn_count": 0,
        "max_turns": 40,
        "question_bank": [],
        "current_question": None,
        "projects_asked": [],
        "last_answer_quality": "adequate",
        "followup_count": 0,
        "existing_summary": None,
        "should_summarize": False,
        "report": None,
        "fallback_used": False,
        "structured_output": None,
    }
    try:
        result = await _get_graph().ainvoke(
            initial_state, config=tracing.with_callbacks(_config(thread_id))
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception(f"interview.start_failed | session={session_id} | {exc}")
        await _mark_session_failed(session_id, tenant_id, user_id)
        raise HTTPException(status_code=502, detail="面试初始化失败，请稍后重试") from exc

    messages = result.get("messages", [])
    opening = _last_ai_text(messages)
    logger.info(f"interview.session_started | session={session_id} | target={target_position}")
    return success(
        {
            "session_id": session_id,
            "thread_id": thread_id,
            "target_position": target_position,
            "status": "in_progress",
            "current_stage": result.get("current_stage", "warmup"),
            "message": opening,
        }
    )


@router.post("/sessions/{session_id}/chat")
async def chat(
    session_id: str,
    req: ChatRequest,
    _: object = Depends(require_scope(Scope.INTERVIEW_ASK)),  # noqa: B008
    current: CurrentUser = Depends(get_current_user),
) -> Any:
    """学员回答一轮，返回面试官回应。

    说明：追加学员消息并推进状态机；结束轮附五维报告摘要。
    请求：path { session_id }, body { message: str 必填 }
    权限：interview:ask
    返回：reply / current_stage / total_turns / is_finished / report_summary?
    """
    tenant_id, user_id = _identity(current)
    row = await _load_session(session_id, tenant_id, user_id)
    if not row:
        raise HTTPException(status_code=404, detail="面试会话不存在")
    if row["status"] != "in_progress":
        raise HTTPException(status_code=409, detail="面试已结束，不能继续回答")

    thread_id = str(row["thread_id"])
    state_update = {
        "messages": [HumanMessage(content=_message_text(req.message))],
        "user_id": user_id,
        "tenant_id": tenant_id,
        "thread_id": thread_id,
        "session_id": session_id,
    }
    try:
        result = await _get_graph().ainvoke(
            state_update, config=tracing.with_callbacks(_config(thread_id))
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception(f"interview.chat_failed | session={session_id} | {exc}")
        raise HTTPException(status_code=502, detail="面试官暂时无法回应，请重试") from exc

    current_stage = result.get("current_stage", "warmup")
    is_finished = current_stage == "finished"
    response = {
        "session_id": session_id,
        "reply": _last_ai_text(result.get("messages", [])),
        "current_stage": current_stage,
        "total_turns": result.get("total_turn_count", 0),
        "is_finished": is_finished,
    }
    if is_finished:
        report = result.get("report") or {}
        response["report_summary"] = {
            "overall_score": report.get("overall_score", 0),
            "strengths": report.get("strengths", []),
            "improvements": report.get("improvements", []),
        }
    return success(response)


@router.post("/sessions/{session_id}/chat/stream")
async def chat_stream(
    session_id: str,
    req: ChatRequest,
    _: object = Depends(require_scope(Scope.INTERVIEW_ASK)),  # noqa: B008
    current: CurrentUser = Depends(get_current_user),
) -> EventSourceResponse:
    """SSE 流式面试，逐 token 返回面试官回应。

    说明：事件类型 token / stopped / done / error；支持服务端停止标记中断生成。
    请求：path { session_id }, body { message: str 必填 }
    权限：interview:ask
    返回：text/event-stream
    """
    tenant_id, user_id = _identity(current)
    row = await _load_session(session_id, tenant_id, user_id)
    if not row:
        raise HTTPException(status_code=404, detail="面试会话不存在")
    if row["status"] != "in_progress":
        raise HTTPException(status_code=409, detail="面试已结束，不能继续回答")

    thread_id = str(row["thread_id"])
    state_update = {
        "messages": [HumanMessage(content=_message_text(req.message))],
        "user_id": user_id,
        "tenant_id": tenant_id,
        "thread_id": thread_id,
        "session_id": session_id,
    }

    async def event_generator():
        stopped = False
        try:
            # 进入前清掉可能残留的停止标记，避免误停本次生成
            await clear_interview_stop(tenant_id, user_id, session_id)
            graph = _get_graph()
            async for event in graph.astream_events(
                state_update, config=_config(thread_id), version="v2"
            ):
                # 每个事件产出前检查 Redis 停止标记（跨 worker 生效）
                if await is_interview_stopped(tenant_id, user_id, session_id):
                    stopped = True
                    break
                if event["event"] != "on_chat_model_stream":
                    continue
                if event.get("metadata", {}).get("langgraph_node") != "generate_response":
                    continue
                chunk = event["data"].get("chunk")
                chunk_text = _msg_text(chunk) if chunk is not None else ""
                if chunk_text:
                    yield {
                        "data": json.dumps(
                            {"type": "token", "content": chunk_text},
                            ensure_ascii=False,
                        )
                    }

            if stopped:
                yield {"data": json.dumps({"type": "stopped"}, ensure_ascii=False)}
                yield {"data": json.dumps({"type": "done"}, ensure_ascii=False)}
                return

            final = await graph.aget_state(_config(thread_id))
            state = final.values if final else {}
            current_stage = state.get("current_stage", "warmup")
            is_finished = current_stage == "finished"
            done: dict[str, Any] = {
                "type": "done",
                "reply": _last_ai_text(state.get("messages", [])),
                "current_stage": current_stage,
                "total_turns": state.get("total_turn_count", 0),
                "is_finished": is_finished,
            }
            if is_finished:
                report = state.get("report") or {}
                done["report_summary"] = {
                    "overall_score": report.get("overall_score", 0),
                    "strengths": report.get("strengths", []),
                    "improvements": report.get("improvements", []),
                }
            yield {"data": json.dumps(done, ensure_ascii=False)}
        except Exception as exc:  # noqa: BLE001
            logger.exception(f"interview.stream_failed | session={session_id} | {exc}")
            yield {
                "data": json.dumps(
                    {"type": "error", "message": "流式输出异常，请重试"},
                    ensure_ascii=False,
                )
            }
        finally:
            await clear_interview_stop(tenant_id, user_id, session_id)

    return EventSourceResponse(event_generator(), ping=15)


@router.get("/sessions")
async def list_sessions(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    status_filter: str | None = Query(None, alias="status"),
    _: object = Depends(require_scope(Scope.INTERVIEW_PAGE)),  # noqa: B008
    current: CurrentUser = Depends(get_current_user),
) -> Any:
    """分页查询当前用户的面试会话。

    说明：仅返回未删除会话，可按 status 过滤。
    请求：query { page, page_size, status? }
    权限：interview:page
    返回：items / total / page / page_size
    """
    tenant_id, user_id = _identity(current)
    conds = [
        "tenant_id = :tenant_id",
        "user_id = :user_id",
        "status <> 'deleted'",
    ]
    params: dict[str, Any] = {"tenant_id": tenant_id, "user_id": user_id}
    if status_filter:
        conds.append("status = :status")
        params["status"] = status_filter
    where = " AND ".join(conds)

    list_sql = text(
        f"""
        SELECT session_id, thread_id, target_position, status, overall_score,
               finished_at, create_at
        FROM agent_interview_sessions
        WHERE {where}
        ORDER BY create_at DESC
        LIMIT :limit OFFSET :offset
        """
    )
    count_sql = text(f"SELECT count(*) FROM agent_interview_sessions WHERE {where}")
    async with session_scope() as session:
        rows, total = await fetch_page(
            session, list_sql, count_sql, params, page=page, page_size=page_size
        )
    return success(
        {
            "items": [_session_item(r) for r in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    )


@router.post("/chat/stop", summary="停止当前会话的流式生成")
async def stop_chat(
    req: StopChatRequest,
    _: object = Depends(require_scope(Scope.INTERVIEW_ASK)),  # noqa: B008
    current: CurrentUser = Depends(get_current_user),
) -> Any:
    """请求停止指定会话的流式生成。

    说明：写 Redis 停止标记，流式生成器在下一个事件前中断（跨 worker 生效）。
    请求：body { session_id: str 必填 }
    权限：interview:ask
    返回：{ session_id, stopped }
    """
    tenant_id, user_id = _identity(current)
    await set_interview_stop(tenant_id, user_id, req.session_id)
    return success({"session_id": req.session_id, "stopped": True})


@router.get("/sessions/{session_id}", summary="会话详情（含历史消息）")
async def get_session(
    session_id: str,
    _: object = Depends(require_scope(Scope.INTERVIEW_VIEW)),  # noqa: B008
    current: CurrentUser = Depends(get_current_user),
) -> Any:
    """获取会话详情与历史消息回放。

    说明：从 checkpointer 最新快照回放 Human/AI 消息，过滤内部哨兵。
    请求：path { session_id }
    权限：interview:view
    返回：会话元信息 + messages[]
    """
    tenant_id, user_id = _identity(current)
    row = await _load_session(session_id, tenant_id, user_id)
    if not row:
        raise HTTPException(status_code=404, detail="面试会话不存在")
    messages = await _history_messages(str(row["thread_id"]))
    return success({**_session_item(row), "messages": messages})


@router.delete("/sessions/{session_id}", summary="删除面试会话")
async def delete_session(
    session_id: str,
    _: object = Depends(require_scope(Scope.INTERVIEW_DELETE)),  # noqa: B008
    current: CurrentUser = Depends(get_current_user),
) -> Any:
    """删除面试会话（软删归档）。

    说明：业务表 status=deleted，关联 agent_thread 归档，checkpointer 保留可恢复。
    请求：path { session_id }
    权限：interview:delete
    返回：{ session_id, status }
    """
    tenant_id, user_id = _identity(current)
    row = await _load_session(session_id, tenant_id, user_id)
    if not row:
        raise HTTPException(status_code=404, detail="面试会话不存在")
    affected = await _archive_session(
        session_id=session_id,
        thread_id=str(row["thread_id"]),
        tenant_id=tenant_id,
        user_id=user_id,
    )
    if affected == 0:
        raise HTTPException(status_code=404, detail="面试会话不存在")
    await clear_interview_stop(tenant_id, user_id, session_id)
    return success({"session_id": session_id, "status": "deleted"})


@router.get("/sessions/{session_id}/report")
async def get_report(
    session_id: str,
    _: object = Depends(require_scope(Scope.INTERVIEW_VIEW)),  # noqa: B008
    current: CurrentUser = Depends(get_current_user),
) -> Any:
    """获取面试报告；未结束时返回 409。

    说明：报告为结构化五维评分与建议。
    请求：path { session_id }
    权限：interview:view
    返回：overall_score / dimensions / strengths / improvements / 建议字段
    """
    tenant_id, user_id = _identity(current)
    row = await _load_session(session_id, tenant_id, user_id)
    if not row:
        raise HTTPException(status_code=404, detail="面试记录不存在")
    if row["status"] != "finished":
        raise HTTPException(status_code=409, detail="面试尚未结束，报告生成中")

    raw = row.get("report")
    report = raw if isinstance(raw, dict) else (json.loads(raw) if raw else {})
    return success(
        {
            "session_id": session_id,
            "thread_id": str(row["thread_id"]),
            "target_position": row["target_position"],
            "status": row["status"],
            "overall_score": row.get("overall_score"),
            "dimensions": report.get("dimensions", []),
            "strengths": report.get("strengths", []),
            "improvements": report.get("improvements", []),
            "overall_comment": report.get("overall_comment", ""),
            "recommended_topics": report.get("recommended_topics", []),
            "next_step_advice": report.get("next_step_advice", ""),
            "finished_at": _iso(row.get("finished_at")),
        }
    )
