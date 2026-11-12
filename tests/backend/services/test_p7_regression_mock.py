"""P7 回归（无 PG，mock DB/LLM）：锁死 exam/resume 任务入口、RAGAS handler 状态机、四结果页端点收口。

真实库版本见 tests/backend/broker/test_qa_ragas_realdb.py（需 TEST_DATABASE_URL）。
本文件聚焦「行为契约」：
  - 任务入口 enqueue 必带 turn_id + 正确 task type（Step 9 联调早版漏 turn_id 导致运行时失败）；
  - RAGAS handler 在 pending→success / 已处理→跳过 / 结果缺失→failed 三态正确；
  - 四结果页（qa/exam/resume/interview）端点已装配，收口不丢路由。
"""
from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

from backend.agents.qa.ragas_eval import RagasScores
from backend.broker.envelope import MessageHeader, TaskMessage
from backend.broker.handlers.qa_ragas import handle_qa_ragas_review
from backend.broker.types import TaskType
from backend.services import unified_task_service as svc


# ---------- 1. exam / resume 任务入口：enqueue 必带 turn_id + 正确 task type ----------

def _fake_spec(agent_type: str) -> types.SimpleNamespace:
    return types.SimpleNamespace(agent_type=agent_type)


async def _start_unified(agent_type: str, turn_id: str, enq: AsyncMock):
    with patch.object(svc, "session_scope") as sm:
        cm = AsyncMock()
        session = MagicMock()
        res = MagicMock()
        res.fetchone.return_value = ("existing",)
        session.execute = AsyncMock(return_value=res)
        cm.__aenter__.return_value = session
        cm.__aexit__.return_value = False
        sm.return_value = cm
        with patch.object(svc, "_object_key_of", new_callable=AsyncMock, return_value="k"), \
             patch.object(svc, "_entry_value", return_value="EXAM-ID"), \
             patch.object(svc, "enqueue_task", enq):
            return await svc.start_unified_task(
                spec=_fake_spec(agent_type),
                turn_id=turn_id,
                entry=None,
                attachments=[],
                tenant_id=6,
                user_id=4,
                trace_id="T",
                thread_id="U-1",
            )


async def test_start_exam_enqueues_exam_review_with_turn_id() -> None:
    enq = AsyncMock()
    res = await _start_unified("exam", "T-EXAM", enq)
    assert res["artifact_type"] == "exam"
    assert enq.call_args.args[0] == TaskType.EXAM_REVIEW
    assert enq.call_args.kwargs["data"]["turn_id"] == "T-EXAM"


async def test_start_resume_enqueues_resume_review_with_turn_id() -> None:
    enq = AsyncMock()
    res = await _start_unified("resume", "T-RESUME", enq)
    assert res["artifact_type"] == "resume"
    assert enq.call_args.args[0] == TaskType.RESUME_REVIEW
    assert enq.call_args.kwargs["data"]["turn_id"] == "T-RESUME"


# ---------- 2. RAGAS handler 状态机 ----------

@pytest.fixture
def _patched_ragas(monkeypatch):
    dao = MagicMock()
    dao.get_eval = AsyncMock(return_value={"status": "pending"})
    dao.get = AsyncMock(
        return_value={
            "question": "Q",
            "answer": "A",
            "retrieved_contexts": "[]",
            "reference_answer": "R",
        }
    )
    dao.finish_eval = AsyncMock(return_value=1)
    monkeypatch.setattr("backend.broker.handlers.qa_ragas.QaResultDao", dao)
    monkeypatch.setattr(
        "backend.broker.handlers.qa_ragas.authorize_task", AsyncMock()
    )
    return dao


def _ragas_msg(eval_id: str = "E1", qa_result_id: str = "R1", retry: int = 0) -> TaskMessage:
    return TaskMessage(
        key="qa.ragas_review",
        type=TaskType.QA_RAGAS_REVIEW,
        header=MessageHeader(tenant_id=1, user_id=1, retry_count=retry),
        data={"eval_id": eval_id, "qa_result_id": qa_result_id},
    )


async def test_ragas_handler_pending_to_success(_patched_ragas) -> None:
    import backend.agents.qa.ragas_eval as re_mod

    with patch.object(re_mod, "get_structured_llm") as m:
        m.return_value.ainvoke = AsyncMock(
            return_value=RagasScores(
                faithfulness=0.9,
                answer_relevancy=0.8,
                context_precision=0.7,
                context_recall=0.6,
                answer_correctness=0.85,
            )
        )
        await handle_qa_ragas_review(_ragas_msg())

    args = _patched_ragas.finish_eval.call_args.kwargs
    assert args["status"] == "success"
    assert args["faithfulness"] == 0.9
    assert args["answer_correctness"] == 0.85


async def test_ragas_handler_skips_when_already_processed(_patched_ragas) -> None:
    _patched_ragas.get_eval.return_value = {"status": "success"}
    await handle_qa_ragas_review(_ragas_msg())
    _patched_ragas.finish_eval.assert_not_called()


async def test_ragas_handler_failed_when_result_missing(_patched_ragas) -> None:
    _patched_ragas.get.return_value = None
    await handle_qa_ragas_review(_ragas_msg())
    args = _patched_ragas.finish_eval.call_args.kwargs
    assert args["status"] == "failed"
    assert "不存在" in (args["error_msg"] or "")


# ---------- 3. 四结果页端点收口（已装配，不丢路由） ----------

def test_four_result_pages_registered() -> None:
    from fastapi import FastAPI

    from backend.api.router import api_router

    app = FastAPI()
    app.include_router(api_router)
    paths = app.openapi()["paths"]
    expected = [
        "/api/v1/tenant/qa/results",
        "/api/v1/tenant/qa/results/{result_id}",
        "/api/v1/tenant/qa/results/{result_id}/review",
        "/api/v1/tenant/qa/results/{result_id}/quality",
        "/api/v1/tenant/exam/my-submissions",
        "/api/v1/tenant/exam/submissions/{submission_id}/confirm",
        "/api/v1/tenant/resume/reviews",
        "/api/v1/tenant/interview/sessions",
    ]
    for p in expected:
        assert p in paths, f"结果页端点未装配：{p}"
