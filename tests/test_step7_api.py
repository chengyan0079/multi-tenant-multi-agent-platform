"""Step 7 集成测试：12 /unified/* 端点接线、scope 拦截、SSE 帧、附件、会话 CRUD。

不连真实库 / LLM：用 TestClient 注入 fake app_state 与 fake 编排图，仅校验路由装配、鉴权、
协议转换。Step 6 已对编排内核做 DB-free 单测，本文件聚焦接入层收口正确性。
鉴权通过 app.dependency_overrides[get_current_user] 注入，避免改动被 Depends 闭包捕获的引用。
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.exceptions import register_exception_handlers
from backend.api.router import api_router
from backend.api.v1.tenant.agent import unified_deps
from backend.middleware.auth import CurrentUser, get_current_user
from backend.observability.exception import ErrCode
from backend.orchestration.agent_registry import AgentRegistry
from backend.orchestration.agent_spec import AgentSpec
from backend.orchestration.unified_schemas import (
    DoneEvent,
    MetaEvent,
    RoutingDecisionEvent,
    TokenEvent,
    UnifiedEvent,
)
from backend.security.rbac import Scope


def _user(scopes: list[str]) -> CurrentUser:
    return CurrentUser(
        user_id=1,
        tenant_id=1,
        home_tenant_id=1,
        role_name="tenant_admin",
        is_super_admin=False,
        is_tenant_admin=True,
        scopes=scopes,
    )


class FakeGraph:
    """替代真实 UnifiedGraph：产出固定事件序列，验证 SSE 帧拼接。"""

    def __init__(self, *_, **__):
        self.captured: dict | None = None

    async def run_stream(self, *, session_id, tenant_id, user_id, message, agent_type=None, entry=None, attachments=None):
        self.captured = {
            "session_id": session_id,
            "tenant_id": tenant_id,
            "user_id": user_id,
            "message": message,
            "agent_type": agent_type,
        }
        yield UnifiedEvent(
            event_type="routing_decision",
            payload=RoutingDecisionEvent(
                agent_type="qa", source="rule", execution_mode="stream", spec_version="v2"
            ),
        )
        yield UnifiedEvent(event_type="token", payload=TokenEvent(content="你好"))
        yield UnifiedEvent(
            event_type="meta",
            payload=MetaEvent(thread_id="t1", turn_id="u1", turn_index=1),
        )
        yield UnifiedEvent(event_type="done", payload=DoneEvent())


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(api_router)
    register_exception_handlers(app)
    registry = SimpleNamespace(
        specs=lambda tenant_id=None: [AgentSpec(agent_type="qa", display_name="AI 问答")],
        spec_for=lambda a: AgentSpec(agent_type="qa", display_name="AI 问答") if a else None,
        is_enabled_for_tenant=lambda *_, **__: True,
    )
    app.state.app_state = SimpleNamespace(agent_registry=registry, orchestrator=object())
    return app


def _client(app: FastAPI, scopes) -> TestClient:
    if scopes is not None:
        user = _user(scopes)
        # get_current_user 被 Depends 闭包捕获，只能通过 dependency_overrides 注入
        app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def _frames(text: str) -> list[dict]:
    import json

    out: list[dict] = []
    for line in text.splitlines():
        if line.startswith("data:"):
            out.append(json.loads(line[len("data:") :].strip()))
    return out


def test_unified_paths_registered():
    app = _build_app()
    schema = app.openapi()["paths"]
    expected = [
        "/api/v1/tenant/unified/chat/stream",
        "/api/v1/tenant/unified/chat/stop",
        "/api/v1/tenant/unified/attachments",
        "/api/v1/tenant/unified/agents",
        "/api/v1/tenant/unified/sessions",
        "/api/v1/tenant/unified/sessions/{thread_id}",
        "/api/v1/tenant/unified/sessions/{thread_id}/artifacts",
        "/api/v1/tenant/unified/session-admin/sessions",
        "/api/v1/tenant/unified/session-admin/sessions/{thread_id}",
    ]
    for p in expected:
        assert p in schema, f"缺少端点 {p}"


def test_agents_requires_auth():
    # 不注入 override → 真实鉴权缺 token，应 401
    app = _build_app()
    assert TestClient(app).get("/api/v1/tenant/unified/agents").status_code == 401


def test_agents_forbids_without_scope():
    app = _build_app()
    # 注入了用户但没有 unified:ask → require_scope 抛 TenantError → 200 + code=FORBIDDEN
    resp = _client(app, ["some:other"]).get("/api/v1/tenant/unified/agents")
    assert resp.status_code == 200
    assert resp.json()["code"] == ErrCode.FORBIDDEN


def test_agents_returns_cards():
    app = _build_app()
    resp = _client(app, [Scope.UNIFIED_ASK]).get("/api/v1/tenant/unified/agents")
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert isinstance(body, list) and body
    assert body[0]["agent_type"] == "qa"
    assert body[0]["display_name"] == "AI 问答"


def test_chat_stream_sse_frames(monkeypatch):
    fake = FakeGraph()
    monkeypatch.setattr(unified_deps, "build_unified_graph", lambda app_state: fake)
    app = _build_app()
    resp = _client(app, [Scope.UNIFIED_ASK]).post(
        "/api/v1/tenant/unified/chat/stream",
        json={"session_id": "s1", "message": "你好", "agent_type": "qa"},
    )
    assert resp.status_code == 200
    frames = _frames(resp.text)
    types = [f["type"] for f in frames]
    assert types[0] == "routing_decision"
    assert "token" in types
    assert types[-1] == "done"
    assert fake.captured["message"] == "你好"


def test_attachments_returns_ref(monkeypatch):
    from backend.services.attachment_service import AttachmentUploadResponse

    async def fake_upload(*, file, tenant_id, user_id, accept_exts=None):
        return AttachmentUploadResponse(file_ref="f1", filename="a.docx", size=10, content_type="x")

    monkeypatch.setattr(
        "backend.api.v1.tenant.agent.unified_chat.upload_attachment", fake_upload
    )
    app = _build_app()
    resp = _client(app, [Scope.UNIFIED_ASK]).post(
        "/api/v1/tenant/unified/attachments",
        files={"file": ("a.docx", b"x" * 10, "application/vnd.openxmlformats")},
        data={"agent_type": "exam"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["file_ref"] == "f1"


def test_sessions_list_and_admin_scope(monkeypatch):
    from backend.data.dao.agent.thread_dao import ThreadDao
    from backend.data.dao.agent.unified_turn_dao import UnifiedTurnDao

    row = {
        "id": "t1", "session_key": "s1", "title": "会话1", "status": "active",
        "created_at": None, "updated_at": None, "turn_count": 2, "last_agent_type": "qa",
    }

    async def fake_list(*, tenant_id, user_id, page=1, page_size=20, status=None):
        return [row], 1

    async def fake_list_admin(*, tenant_id, page=1, page_size=20, status=None):
        return [row], 1

    monkeypatch.setattr(ThreadDao, "list_sessions", staticmethod(fake_list))
    monkeypatch.setattr(ThreadDao, "list_sessions_admin", staticmethod(fake_list_admin))
    monkeypatch.setattr(
        UnifiedTurnDao, "list_recent_by_thread", staticmethod(AsyncMock(return_value=[]))
    )
    monkeypatch.setattr(
        UnifiedTurnDao, "list_artifacts", staticmethod(AsyncMock(return_value=[]))
    )

    app = _build_app()
    # 用户无 session-admin scope → 管理端 TenantError → 200 + code=FORBIDDEN
    resp = _client(app, [Scope.UNIFIED_ASK]).get(
        "/api/v1/tenant/unified/session-admin/sessions"
    )
    assert resp.status_code == 200
    assert resp.json()["code"] == ErrCode.FORBIDDEN
    # 聊天框内列表（unified:ask）正常
    resp = _client(app, [Scope.UNIFIED_ASK]).get("/api/v1/tenant/unified/sessions")
    assert resp.status_code == 200
    assert resp.json()["data"]["items"][0]["thread_id"] == "t1"

    # 带上 session-admin scope → 管理端 200
    assert _client(app, [Scope.UNIFIED_ASK, Scope.UNIFIED_SESSION_PAGE]).get(
        "/api/v1/tenant/unified/session-admin/sessions"
    ).status_code == 200


def test_turn_dao_admin_branch_omits_user_filter(monkeypatch):
    """管理端按 thread 读回放时 user_id 为空，SQL 不应再带 :user_id 参数（否则缺参报错）。"""
    import asyncio
    from contextlib import asynccontextmanager

    from backend.data.dao.agent import unified_turn_dao as turn_mod

    captured: dict = {}

    @asynccontextmanager
    async def _fake_session_scope():
        yield object()

    async def _fake_fetch_all(_session, sql, params):
        captured["sql"] = str(sql)
        captured["params"] = params
        return []

    monkeypatch.setattr(turn_mod, "session_scope", _fake_session_scope)
    monkeypatch.setattr(turn_mod, "fetch_all", _fake_fetch_all)

    # 管理端：user_id=None → 不带 user 过滤，参数里无 user_id
    asyncio.run(
        turn_mod.UnifiedTurnDao.list_recent_by_thread(
            thread_id="t1", tenant_id=1, user_id=None
        )
    )
    assert "user_id" not in captured["params"]
    assert ":user_id" not in captured["sql"]

    # 普通用户：user_id 给定 → 参数含 user_id
    asyncio.run(
        turn_mod.UnifiedTurnDao.list_recent_by_thread(
            thread_id="t1", tenant_id=1, user_id=7
        )
    )
    assert captured["params"]["user_id"] == 7
    assert ":user_id" in captured["sql"]


# --------------------------------------------------------------------------- #
# 4 卡片 + 模板：注入真实 4-spec 注册表，/agents 返回能力卡且各自带模板问题
# --------------------------------------------------------------------------- #
def test_agents_returns_four_cards_with_templates():
    reg = AgentRegistry()
    for at, name, desc, tmpl in [
        ("qa", "智能问答", "问答", ("怎么用 LangGraph 做检查点？", "解释 RAG 的召回策略")),
        ("interview", "模拟面试", "面试", ("我想练习后端面试", "来一场 Java 面试")),
        ("exam", "考试批改", "考试", ("给我出一套数据结构试卷",)),
        ("resume", "简历诊断", "简历", ("帮我优化简历",)),
    ]:
        reg.register(
            at, lambda: None,
            spec=AgentSpec(agent_type=at, display_name=name, description=desc,
                           intent_labels=(at,), templates=tmpl),
        )
    reg.register(
        "multi_agent", lambda: None,
        spec=AgentSpec(agent_type="multi_agent", display_name="组合任务",
                       description="串联", intent_labels=("multi_agent",),
                       execution_mode="pipeline"),
    )
    reg._rebuild_derived()

    app = _build_app()
    app.state.app_state = SimpleNamespace(agent_registry=reg, orchestrator=object())
    resp = _client(app, [Scope.UNIFIED_ASK]).get("/api/v1/tenant/unified/agents")
    assert resp.status_code == 200
    body = resp.json()["data"]
    types = {c["agent_type"] for c in body}
    assert {"qa", "interview", "exam", "resume"} <= types
    for c in body:
        assert c["agent_type"] in {"qa", "interview", "exam", "resume", "multi_agent"}
        if c["agent_type"] != "multi_agent":
            assert c["templates"], f"{c['agent_type']} 卡片缺少模板问题"


# --------------------------------------------------------------------------- #
# 停止标记：/chat/stop 置内存标记，供流式生成循环中断
# --------------------------------------------------------------------------- #
def test_chat_stop_sets_flag(monkeypatch):
    from backend.api.v1.tenant.agent.unified_chat import _STOP_FLAGS

    app = _build_app()
    resp = _client(app, [Scope.UNIFIED_ASK]).post(
        "/api/v1/tenant/unified/chat/stop", json={"session_id": "stop-s1"}
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["ok"] is True
    assert _STOP_FLAGS.get("stop-s1") is True
    _STOP_FLAGS.pop("stop-s1", None)


# --------------------------------------------------------------------------- #
# 4 结果页代表：qa 结果列表 / 详情（monkeypatch DAO，验证接口收口）
# --------------------------------------------------------------------------- #
def test_qa_results_list_and_detail(monkeypatch):
    from backend.data.dao.business.qa_result_dao import QaResultDao

    row = {
        "id": "r1", "tenant_id": 1, "user_id": 2, "session_id": "s1",
        "thread_id": "U1", "agent_type": "qa", "question": "什么是 RAG？",
        "answer": "检索增强生成", "answer_mode": "rag", "query_type": "qa",
        "confidence": 0.9, "status": "done", "latency_ms": 123,
        "created_at": None, "updated_at": None,
    }

    async def fake_list(*, tenant_id, session_id=None, status=None, page=1, page_size=20):
        return [row], 1

    async def fake_get(*, result_id, tenant_id):
        return row

    monkeypatch.setattr(QaResultDao, "list_paged", staticmethod(fake_list))
    monkeypatch.setattr(QaResultDao, "get", staticmethod(fake_get))

    app = _build_app()
    resp = _client(app, [Scope.QA_RESULT_PAGE]).get("/api/v1/tenant/qa/results")
    assert resp.status_code == 200
    assert resp.json()["data"]["items"][0]["id"] == "r1"

    resp = _client(app, [Scope.QA_RESULT_VIEW]).get("/api/v1/tenant/qa/results/r1")
    assert resp.status_code == 200
    assert resp.json()["data"]["id"] == "r1"
