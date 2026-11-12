"""P7 真实回归（④余）：resume 超时扫描在真实 PG 下把 processing + 超时的评审标记 failed。

沿用 tests/conftest.py 真实 PG 基座。仅覆盖「扫描落库」这一真实行为：种子一条
status=processing 且 create_at 远早于超时阈值的记录，调用 SchedulerManager._scan_resume_timeout，
断言该记录被翻转为 failed。无 PG 环境下跳过。

注意：业务表 id / turn_id 为 UUID 列，种子值须用真实 uuid。
"""
from __future__ import annotations

import os
import uuid6
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import text

from backend.server.managers import scheduler_manager as sch

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="需 TEST_DATABASE_URL 真实 PG（resume 超时扫描落库）",
)


async def test_resume_timeout_marks_failed(pg_session, monkeypatch) -> None:
    rid = str(uuid6.uuid7())
    try:
        await pg_session.execute(
            text(
                "INSERT INTO agent_resume_reviews "
                "(id, tenant_id, user_id, turn_id, pdf_minio_path, status, "
                " create_user_id, update_user_id, create_tenant_id, update_tenant_id, create_at) "
                "VALUES (:id, 6, 4, :tid, 'k', 'processing', 4, 4, 6, 6, "
                "now() - make_interval(mins => 60))"
            ),
            {"id": rid, "tid": str(uuid6.uuid7())},
        )
        # 扫描依赖 app_state.settings.scheduler.resume_timeout_min
        fake_settings = SimpleNamespace(
            scheduler=SimpleNamespace(resume_timeout_min=10)
        )
        monkeypatch.setattr(sch.app_state, "settings", fake_settings, raising=False)
        # 让扫描走真实 PG 会话
        with patch.object(sch, "session_scope") as sm:
            cm = AsyncMock()
            cm.__aenter__.return_value = pg_session
            cm.__aexit__.return_value = False
            sm.return_value = cm
            await sch.SchedulerManager()._scan_resume_timeout()

        row = (
            await pg_session.execute(
                text("SELECT status FROM agent_resume_reviews WHERE id=:id"),
                {"id": rid},
            )
        ).fetchone()
        assert row is not None
        assert row[0] == "failed"
    finally:
        await pg_session.execute(
            text("DELETE FROM agent_resume_reviews WHERE id=:id"), {"id": rid}
        )
        await pg_session.commit()
