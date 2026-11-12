"""P7 真实回归（④余）：exam HITL 提交落在真实 PG —— start_unified_task(exam) 写入
agent_exam_submissions 且携带 turn_id（UUID 列，验证真实库不丢字段）。

沿用 tests/conftest.py 真实 PG 基座。mock 边界：enqueue / _object_key_of / _entry_value，
DB 与 INSERT 走真实会话。无 PG 环境下跳过。

覆盖 exam HITL 全链路的第一环（提交→落库带 turn_id）；复核/发布需 LLM+graph，属 E2E 段。
"""
from __future__ import annotations

import os
import uuid6
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import text

from backend.services import unified_task_service as svc

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="需 TEST_DATABASE_URL 真实 PG（exam 提交落库）",
)


async def test_exam_submit_persists_turn_id(pg_session, monkeypatch) -> None:
    exam_id = str(uuid6.uuid7())
    turn_id = str(uuid6.uuid7())
    try:
        # start_unified_task 先校验 exam 存在
        await pg_session.execute(
            text(
                "INSERT INTO agent_exams "
                "(id, tenant_id, title, is_active, "
                " create_user_id, update_user_id, create_tenant_id, update_tenant_id) "
                "VALUES (:id, 6, 'E', true, 4, 4, 6, 6)"
            ),
            {"id": exam_id},
        )
        with patch.object(svc, "session_scope") as sm:
            cm = AsyncMock()
            cm.__aenter__.return_value = pg_session
            cm.__aexit__.return_value = False
            sm.return_value = cm
            with patch.object(
                svc, "_object_key_of", new_callable=AsyncMock, return_value="k"
            ), patch.object(svc, "_entry_value", return_value=exam_id), patch.object(
                svc, "enqueue_task", AsyncMock()
            ) as enq:
                res = await svc.start_unified_task(
                    spec=SimpleNamespace(agent_type="exam"),
                    turn_id=turn_id,
                    entry=None,
                    attachments=[],
                    tenant_id=6,
                    user_id=4,
                    trace_id="T",
                    thread_id="U-1",
                )
        assert res["artifact_type"] == "exam"
        assert enq.call_args.args[0].value == "exam.review"
        row = (
            await pg_session.execute(
                text(
                    "SELECT turn_id, status FROM agent_exam_submissions "
                    "WHERE exam_id=:e"
                ),
                {"e": exam_id},
            )
        ).fetchone()
        assert row is not None
        assert row[0] == turn_id
        assert row[1] == "ai_processing"
    finally:
        await pg_session.execute(
            text("DELETE FROM agent_exam_submissions WHERE exam_id=:e"), {"e": exam_id}
        )
        await pg_session.execute(
            text("DELETE FROM agent_exams WHERE id=:id"), {"id": exam_id}
        )
        await pg_session.commit()
