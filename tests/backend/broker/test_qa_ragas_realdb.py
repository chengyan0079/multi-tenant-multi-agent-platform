"""RAGAS 真实库回归：仅 mock LLM 打分，DB 走真实 PostgreSQL。需 TEST_DATABASE_URL。

锁死「问答结果 → 触发 RAGAS → 评估记录 pending→success 且五项指标落库」这条 P7 回归主线，
避免评分链路静默失败（对接完成口径要求端到端验证）。无 PG 环境下整文件跳过。

注意：业务表 id / qa_result_id 均为 UUID 列，种子值必须用真实 uuid（不能用占位字符串）。
"""
from __future__ import annotations

import os
import uuid6
from unittest.mock import AsyncMock, patch

import pytest

from backend.agents.qa.ragas_eval import RagasScores
from backend.broker.envelope import MessageHeader, TaskMessage
from backend.broker.handlers.qa_ragas import handle_qa_ragas_review
from backend.broker.types import TaskType
from backend.data.dao.business.qa_result_dao import QaResultDao

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="需 TEST_DATABASE_URL 真实 PG（ORM 含 PG 专属 SQL，无 sqlite 替代）",
)

_AUDIT = {
    "create_user_id": 1,
    "update_user_id": 1,
    "create_tenant_id": 1,
    "update_tenant_id": 1,
}


async def test_ragas_handler_writes_scores_to_db(pg_session) -> None:
    result_id = str(uuid6.uuid7())
    eval_id = str(uuid6.uuid7())
    await QaResultDao.insert(
        record={
            "id": result_id,
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
    await QaResultDao.insert_eval(
        eval_id=eval_id,
        record={
            "qa_result_id": result_id,
            "trace_id": "t",
            "tenant_id": 1,
            "evaluator": "ragas",
            "evaluator_model": "gpt",
            "dataset_version": "v1",
            "status": "pending",
            "error_msg": None,
            "eval_at": None,
        },
        audit=_AUDIT,
    )

    msg = TaskMessage(
        key="qa.ragas_review",
        type=TaskType.QA_RAGAS_REVIEW,
        header=MessageHeader(tenant_id=1, user_id=1, retry_count=0),
        data={"eval_id": eval_id, "qa_result_id": result_id},
    )

    with patch("backend.agents.qa.ragas_eval.get_structured_llm") as m:
        m.return_value.ainvoke = AsyncMock(
            return_value=RagasScores(
                faithfulness=0.9,
                answer_relevancy=0.8,
                context_precision=0.7,
                context_recall=0.6,
                answer_correctness=0.85,
                reason="ok",
            )
        )
        await handle_qa_ragas_review(msg)

    row = await QaResultDao.get_eval(eval_id)
    assert row is not None, "评估记录应存在"
    assert row["status"] == "success"
    assert row["faithfulness"] == pytest.approx(0.9, abs=1e-6)
    assert row["answer_correctness"] == pytest.approx(0.85, abs=1e-6)
