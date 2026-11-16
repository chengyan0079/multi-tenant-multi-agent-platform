"""P7 真实回归（④余）：4 结果页数据层在真实 PG 可写可读。

沿用 tests/conftest.py 真实 PG 基座。qa_results 走真实 DAO（insert→list_paged→get）做完整往返；
exam_submissions / resume_reviews / interview_sessions 各种子一行并查回，验证四结果页的底层
表在真实 PG 下可写入、可查询。端点层已在无头测试 test_p7_regression_mock.py 锁定收口。
无 PG 环境下跳过。

注意：业务表 id / turn_id / exam_id 等均 UUID 列，种子值须用真实 uuid。
"""
from __future__ import annotations

import os
import uuid6
from sqlalchemy import text

import pytest

from backend.data.dao.business.qa_result_dao import QaResultDao

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="需 TEST_DATABASE_URL 真实 PG（4 结果页数据层）",
)

_AUDIT = {
    "create_user_id": 1,
    "update_user_id": 1,
    "create_tenant_id": 1,
    "update_tenant_id": 1,
}


async def test_qa_result_dao_roundtrip(pg_session) -> None:
    rid = str(uuid6.uuid7())
    try:
        await QaResultDao.insert(
            record={
                "id": rid,
                "trace_id": "t",
                "tenant_id": 1,
                "user_id": 1,
                "turn_id": str(uuid6.uuid7()),
                "agent_type": "qa",
                "question": "Q",
                "answer": "A",
                "answer_mode": "direct",
                "query_type": "qa",
                "confidence": 0.9,
                "retrieved_contexts": [],
                "sources": [],
                "reference_answer": "ref",
                "latency_ms": 1,
                "token_usage": {},
                "enable_web_search": False,
                "status": "success",
                "error_msg": None,
                "extra": {},
            },
            audit=_AUDIT,
        )
        rows, total = await QaResultDao.list_paged(
            tenant_id=1, page=1, page_size=10
        )
        assert total >= 1
        assert any(r["id"] == rid for r in rows)
        detail = await QaResultDao.get(result_id=rid, tenant_id=1)
        assert detail["id"] == rid
    finally:
        await pg_session.execute(
            text("DELETE FROM agent_qa_results WHERE id=:id"), {"id": rid}
        )
        await pg_session.commit()


async def test_other_result_pages_queryable(pg_session) -> None:
    eid, e_exam, e_turn = str(uuid6.uuid7()), str(uuid6.uuid7()), str(uuid6.uuid7())
    sid, s_turn = str(uuid6.uuid7()), str(uuid6.uuid7())
    iid = str(uuid6.uuid7())
    try:
        await pg_session.execute(
            text(
                "INSERT INTO agent_exam_submissions "
                "(id, tenant_id, exam_id, user_id, turn_id, source, word_minio_path, "
                " status, submitted_at, published_at, weak_points, weak_points_summary, "
                " create_user_id, update_user_id, create_tenant_id, update_tenant_id) "
                "VALUES (:id, 1, :eid, 1, :tid, 'word', 'k', 'ai_processing', "
                "now(), now(), '[]', '', 1, 1, 1, 1)"
            ),
            {"id": eid, "eid": e_exam, "tid": e_turn},
        )
        await pg_session.execute(
            text(
                "INSERT INTO agent_resume_reviews "
                "(id, tenant_id, user_id, turn_id, pdf_minio_path, status, "
                " create_user_id, update_user_id, create_tenant_id, update_tenant_id) "
                "VALUES (:id, 1, 1, :tid, 'k', 'processing', 1, 1, 1, 1)"
            ),
            {"id": sid, "tid": s_turn},
        )
        await pg_session.execute(
            text(
                "INSERT INTO agent_interview_sessions "
                "(id, tenant_id, status, create_user_id, update_user_id, "
                " create_tenant_id, update_tenant_id) "
                "VALUES (:id, 1, 'in_progress', 1, 1, 1, 1)"
            ),
            {"id": iid},
        )
        for tbl, pk in (
            ("agent_exam_submissions", eid),
            ("agent_resume_reviews", sid),
            ("agent_interview_sessions", iid),
        ):
            row = (
                await pg_session.execute(
                    text(f"SELECT id FROM {tbl} WHERE id=:id"), {"id": pk}
                )
            ).fetchone()
            assert row is not None and row[0] == pk
    finally:
        for tbl, pk in (
            ("agent_exam_submissions", eid),
            ("agent_resume_reviews", sid),
            ("agent_interview_sessions", iid),
        ):
            await pg_session.execute(
                text(f"DELETE FROM {tbl} WHERE id=:id"), {"id": pk}
            )
        await pg_session.commit()
