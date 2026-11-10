"""问答会话接口：列表 / 新增 / 删除 / 详情（含 checkpointer 历史），按用户隔离。"""

from __future__ import annotations

from typing import Any

import uuid6
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from backend.common.logger import logger
from backend.common.response import success
from backend.data.dao.agent.thread_dao import ThreadDao
from backend.middleware.auth import CurrentUser, get_current_user
from backend.security.rbac import Scope
from backend.security.security import require_scope

router = APIRouter(prefix="/qa/sessions", tags=["qa-sessions"])


class SessionCreateIn(BaseModel):
    """新增会话请求（标题可选，前端可传默认名）。"""

    title: str = Field("新会话", max_length=128, description="会话标题（展示用）")


def _iso(value: Any) -> str | None:
    return value.isoformat() if value else None


def _identity(current: CurrentUser) -> tuple[int, int]:
    if current.tenant_id is None:
        raise HTTPException(status_code=403, detail="缺少租户上下文")
    return current.tenant_id, current.user_id


def _session_item(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "thread_id": str(row["id"]),
        "tenant_id": row.get("tenant_id"),
        "user_id": row.get("user_id"),
        "session_id": row.get("session_key"),
        "title": row.get("title") or "新会话",
        "status": row.get("status"),
        "graph_name": row.get("graph_name"),
        "created_at": _iso(row.get("create_at")),
        "updated_at": _iso(row.get("updated_at")),
    }


@router.get("", summary="问答会话列表（分页）")
async def list_sessions(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    _: object = Depends(require_scope(Scope.QA_SESSION_PAGE)),  # noqa: B008
    current: CurrentUser = Depends(get_current_user),
) -> Any:
    """分页查询当前用户的问答会话。

    请求：query { page, page_size }
    权限：qa_session:page
    返回：items / total / page / page_size
    """
    tenant_id, user_id = _identity(current)
    rows, total = await ThreadDao.list_qa_sessions(
        tenant_id=tenant_id, user_id=user_id, page=page, page_size=page_size
    )
    return success(
        {
            "items": [_session_item(r) for r in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    )


@router.post("", status_code=status.HTTP_201_CREATED, summary="新增会话")
async def create_session(
    body: SessionCreateIn | None = None,
    _: object = Depends(require_scope(Scope.QA_SESSION_ADD)),  # noqa: B008
    current: CurrentUser = Depends(get_current_user),
) -> Any:
    """新增问答会话，返回 thread_id 与 session_id。

    请求：body { title?: str }
    权限：qa_session:add
    返回：{ thread_id, session_id, title, status }
    """
    tenant_id, user_id = _identity(current)
    session_key = str(uuid6.uuid7())
    title = (body.title if body else None) or "新会话"
    thread_id = await ThreadDao.create_qa_session(
        tenant_id=tenant_id, user_id=user_id, session_key=session_key, title=title
    )
    return success(
        {
            "thread_id": thread_id,
            "session_id": session_key,
            "title": title,
            "status": "active",
        }
    )


@router.delete("/{thread_id}", summary="删除会话")
async def delete_session(
    thread_id: str,
    _: object = Depends(require_scope(Scope.QA_SESSION_DELETE)),  # noqa: B008
    current: CurrentUser = Depends(get_current_user),
) -> Any:
    """删除（归档）问答会话。

    请求：path { thread_id }
    权限：qa_session:delete
    返回：{ thread_id, status }
    """
    tenant_id, user_id = _identity(current)
    archived = await ThreadDao.archive_qa_session(
        thread_id=thread_id, tenant_id=tenant_id, user_id=user_id
    )
    if archived == 0:
        raise HTTPException(status_code=404, detail="会话不存在")
    return success({"thread_id": thread_id, "status": "archived"})


@router.get("/{thread_id}", summary="会话详情（含历史消息）")
async def get_session(
    thread_id: str,
    _: object = Depends(require_scope(Scope.QA_SESSION_VIEW)),  # noqa: B008
    current: CurrentUser = Depends(get_current_user),
) -> Any:
    """获取会话详情并回放 checkpointer 历史消息。

    请求：path { thread_id }
    权限：qa_session:view
    返回：会话元信息 + messages[]
    """
    tenant_id, user_id = _identity(current)
    row = await ThreadDao.get_qa_session(thread_id=thread_id, tenant_id=tenant_id, user_id=user_id)
    if row is None:
        raise HTTPException(status_code=404, detail="会话不存在")

    # 历史消息来自 LangGraph checkpointer（thread_id 即 agent_thread.id）
    messages: list[dict[str, str]] = []
    try:
        from langchain_core.messages import AIMessage, HumanMessage

        from backend.api.v1.tenant.agent.qa import _get_graph

        snapshot = await _get_graph().aget_state({"configurable": {"thread_id": str(row["id"])}})
        values = snapshot.values if snapshot and snapshot.values else {}
        for msg in values.get("messages", []):
            content = (
                msg.text if hasattr(msg, "text") and not callable(msg.text) else str(msg.content)
            )
            if isinstance(msg, HumanMessage):
                messages.append({"role": "user", "content": content})
            elif isinstance(msg, AIMessage):
                messages.append({"role": "assistant", "content": content})
    except Exception as exc:  # noqa: BLE001 - 历史读取失败不影响会话信息
        logger.exception(f"[qa.sessions] 历史读取失败 thread={thread_id}: {exc}")

    return success({**_session_item(row), "messages": messages})
