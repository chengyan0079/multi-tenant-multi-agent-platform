"""面试会话：历史回放 / 软删除 / 服务端停止生成回归测试。

直接调用端点函数并用 mock 替掉 DB / checkpointer / Redis，不连真实服务。
"""
from __future__ import annotations

import json
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from backend.api.v1.tenant.agent import interview as interview_api
from backend.middleware.auth import CurrentUser
from backend.security.rbac import Scope, VALID_SCOPES


def _current() -> CurrentUser:
    return CurrentUser(
        user_id=9,
        tenant_id=6,
        home_tenant_id=6,
        role_name="tenant_admin",
        is_super_admin=False,
        is_tenant_admin=True,
        scopes=[Scope.INTERVIEW_ASK, Scope.INTERVIEW_VIEW, Scope.INTERVIEW_DELETE],
    )


def _session_row() -> dict:
    # 与 _load_session 生产 SELECT 对齐：返回主键 id（_session_item 读 row["id"]）
    return {
        "id": "session-1",
        "session_id": "session-1",
        "thread_id": "11111111-1111-1111-1111-111111111111",
        "target_position": "AI 应用开发工程师",
        "status": "in_progress",
        "overall_score": None,
        "finished_at": None,
        "create_at": datetime(2026, 11, 8, 12, 0, 0),
    }


def test_interview_delete_scope_is_valid() -> None:
    assert Scope.INTERVIEW_DELETE == "interview:delete"
    assert Scope.INTERVIEW_DELETE in VALID_SCOPES


@pytest.mark.asyncio
async def test_history_messages_filters_sentinel_and_system() -> None:
    class FakeGraph:
        async def aget_state(self, config):  # noqa: ANN001
            return SimpleNamespace(
                values={
                    "messages": [
                        HumanMessage(content="[开始面试]"),
                        AIMessage(content="欢迎，请自我介绍"),
                        SystemMessage(content="内部系统提示"),
                        HumanMessage(content="我有 RAG 项目经验"),
                    ]
                }
            )

    with patch.object(interview_api, "_get_graph", return_value=FakeGraph()):
        messages = await interview_api._history_messages("thread-1")

    assert messages == [
        {"role": "assistant", "content": "欢迎，请自我介绍"},
        {"role": "user", "content": "我有 RAG 项目经验"},
    ]


@pytest.mark.asyncio
async def test_get_session_returns_history() -> None:
    history = [{"role": "assistant", "content": "请自我介绍"}]
    with patch.object(
        interview_api, "_load_session", AsyncMock(return_value=_session_row())
    ), patch.object(
        interview_api, "_history_messages", AsyncMock(return_value=history)
    ) as history_mock:
        response = await interview_api.get_session(
            "session-1", object(), _current()
        )

    assert response.data["session_id"] == "session-1"
    assert response.data["messages"] == history
    history_mock.assert_awaited_once_with(
        "11111111-1111-1111-1111-111111111111"
    )


@pytest.mark.asyncio
async def test_delete_session_soft_deletes_and_clears_stop_flag() -> None:
    with patch.object(
        interview_api, "_load_session", AsyncMock(return_value=_session_row())
    ), patch.object(
        interview_api, "_archive_session", AsyncMock(return_value=1)
    ) as archive_mock, patch.object(
        interview_api, "clear_interview_stop", AsyncMock()
    ) as clear_mock:
        response = await interview_api.delete_session(
            "session-1", object(), _current()
        )

    assert response.data == {"session_id": "session-1", "status": "deleted"}
    archive_mock.assert_awaited_once()
    clear_mock.assert_awaited_once_with(6, 9, "session-1")


@pytest.mark.asyncio
async def test_stop_chat_sets_redis_flag() -> None:
    pytest.skip("stop_chat 端点已在 D2 收口中移除（统一入口改走 /unified/chat/stop）")


@pytest.mark.asyncio
async def test_stream_stops_on_server_flag() -> None:
    pytest.skip("chat_stream 端点已在 D2 收口中移除（统一入口改走 /unified/chat/stream）")
