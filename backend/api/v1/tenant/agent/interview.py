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
    # session_id 现为业务主键 id；thread_id 由 session_key=id 派生（不落库）
    return {
        "session_id": str(row["id"]),
        "thread_id": str(row["thread_id"]) if row.get("thread_id") is not None else None,
        "target_position": row["target_position"],
        "status": row["status"],
        "overall_score": row.get("overall_score"),
        "finished_at": _iso(row.get("finished_at")),
        "created_at": _iso(row.get("create_at")),
    }


async def _load_session(session_id: str, tenant_id: int, user_id: int) -> dict[str, Any] | None:
    async with session_scope() as session:
        row = await fetch_one(
            session,
            text(
                """
                SELECT id, target_position, status, overall_score, report,
                       finished_at, create_at
                FROM agent_interview_sessions
                WHERE id = CAST(:session_id AS uuid)
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
    if row is None:
        return None
    # thread_id 与创建时一致（session_key=业务主键），供 LangGraph checkpointer 续跑
    row = dict(row)
    row["thread_id"] = await ThreadDao.get_or_create(
        tenant_id=tenant_id, user_id=user_id, session_key=str(row["id"])
    )
    return row


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
                 WHERE id = CAST(:session_id AS uuid)
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
    target_position: str,
    resume_review_id: str | None,
) -> None:
    async with session_scope() as session:
        await session.execute(
            text(
                """
                INSERT INTO agent_interview_sessions
                    (id, tenant_id, user_id, target_position, resume_review_id,
                     report, overall_score, status, create_user_id, update_user_id,
                     create_tenant_id, update_tenant_id)
                VALUES
                    (CAST(:session_id AS uuid), :tenant_id, :user_id, :target_position,
                     CAST(:resume_review_id AS uuid), '{}'::json, 0, 'in_progress',
                     :user_id, :user_id, :tenant_id, :tenant_id)
                """
            ),
            {
                "session_id": session_id,
                "tenant_id": tenant_id,
                "user_id": user_id,
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
                    "WHERE id = CAST(:session_id AS uuid) AND tenant_id = :tenant_id "
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
        SELECT id, target_position, status, overall_score, finished_at, create_at
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
