"""P7 回归（无 PG，mock DB/LLM）：RAGAS handler 状态机、问答结果页端点收口。"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

from backend.agents.qa.ragas_eval import RagasScores
from backend.broker.envelope import MessageHeader, TaskMessage
from backend.broker.handlers.qa_ragas import handle_qa_ragas_review
from backend.broker.types import TaskType


@pytest.fixture
def _patched_ragas(monkeypatch):
    dao = MagicMock()
    # 阶段2：评测输入以 eval 记录为准（标准答案必填）
    dao.get_eval = AsyncMock(
        return_value={
            "status": "pending",
            "reference_answer": "R",
            "retrieved_contexts": "[]",
        }
    )
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
    monkeypatch.setattr("backend.broker.handlers.qa_ragas.authorize_task", AsyncMock())
    return dao


def _ragas_msg(eval_id: str = "E1", qa_result_id: str = "R1", retry: int = 0) -> TaskMessage:
    return TaskMessage(
        key="qa.ragas_review",
        type=TaskType.QA_RAGAS_REVIEW,
        header=MessageHeader(tenant_id=1, user_id=1, retry_count=retry),
        data={"eval_id": eval_id, "turn_id": qa_result_id},
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


def test_qa_result_pages_registered() -> None:
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
    ]
    for p in expected:
        assert p in paths, f"结果页端点未装配：{p}"
