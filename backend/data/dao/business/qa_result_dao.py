"""问答结果 DAO：agent_qa_results / agent_qa_ragas_evals 读写，tenant_id 为隔离边界。"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import text

from backend.data.sql import fetch_all, fetch_one, fetch_page, fetch_value, session_scope

_INSERT = text("""
INSERT INTO agent_qa_results (
    id, trace_id, tenant_id, user_id, session_id, thread_id, agent_type,
    question, answer, answer_mode, query_type, confidence,
    retrieved_contexts, sources, reference_answer, latency_ms, token_usage,
    enable_web_search, status, error_msg, extra,
    create_user_id, update_user_id, create_tenant_id, update_tenant_id
) VALUES (
    :id, :trace_id, :tenant_id, :user_id, :session_id, :thread_id, :agent_type,
    :question, :answer, :answer_mode, :query_type, :confidence,
    CAST(:retrieved_contexts AS JSON), CAST(:sources AS JSON), :reference_answer, :latency_ms,
    CAST(:token_usage AS JSON), :enable_web_search, :status, :error_msg, CAST(:extra AS JSON),
    :create_user_id, :update_user_id, :create_tenant_id, :update_tenant_id
)
RETURNING id
""")

_SELECT = text("""
SELECT id, trace_id, tenant_id, user_id, session_id, thread_id, agent_type,
       question, answer, answer_mode, query_type, confidence,
       retrieved_contexts, sources, reference_answer, latency_ms, token_usage,
       enable_web_search, status, error_msg, extra, create_at, updated_at
FROM agent_qa_results
WHERE id = :id AND tenant_id = :tenant_id
""")

_LIST = text("""
SELECT id, trace_id, tenant_id, user_id, session_id, question, answer_mode,
       query_type, confidence, status, latency_ms, create_at
FROM agent_qa_results
WHERE tenant_id = :tenant_id
  AND (CAST(:session_id AS VARCHAR) IS NULL OR session_id = :session_id)
  AND (CAST(:status AS VARCHAR) IS NULL OR status = :status)
ORDER BY create_at DESC
LIMIT :limit OFFSET :offset
""")

_COUNT = text("""
SELECT count(*) FROM agent_qa_results
WHERE tenant_id = :tenant_id
  AND (CAST(:session_id AS VARCHAR) IS NULL OR session_id = :session_id)
  AND (CAST(:status AS VARCHAR) IS NULL OR status = :status)
""")

_UPDATE_REFERENCE = text("""
UPDATE agent_qa_results
SET reference_answer = :reference_answer,
    update_user_id = :update_user_id,
    update_tenant_id = :update_tenant_id
WHERE id = :id AND tenant_id = :tenant_id
""")

_LIST_EVALS = text("""
SELECT id, qa_result_id, trace_id, tenant_id, evaluator, evaluator_model, dataset_version,
       faithfulness, answer_relevancy, context_precision, context_recall, answer_correctness,
       metrics, status, error_msg, eval_at, create_at, updated_at
FROM agent_qa_ragas_evals
WHERE qa_result_id = :qa_result_id AND tenant_id = :tenant_id
ORDER BY create_at DESC
""")

_INSERT_EVAL = text("""
INSERT INTO agent_qa_ragas_evals (
    id, qa_result_id, trace_id, tenant_id, evaluator, evaluator_model, dataset_version,
    metrics, status, error_msg, eval_at,
    create_user_id, update_user_id, create_tenant_id, update_tenant_id
) VALUES (
    :id, :qa_result_id, :trace_id, :tenant_id, :evaluator, :evaluator_model, :dataset_version,
    CAST(:metrics AS JSON), :status, :error_msg, :eval_at,
    :create_user_id, :update_user_id, :create_tenant_id, :update_tenant_id
)
""")

_SELECT_EVAL = text("""
SELECT id, qa_result_id, status FROM agent_qa_ragas_evals WHERE id = :id
""")

_UPDATE_EVAL = text("""
UPDATE agent_qa_ragas_evals
SET status = :status,
    faithfulness = :faithfulness,
    answer_relevancy = :answer_relevancy,
    context_precision = :context_precision,
    context_recall = :context_recall,
    answer_correctness = :answer_correctness,
    metrics = CAST(:metrics AS JSON),
    error_msg = :error_msg,
    eval_at = :eval_at,
    update_user_id = :update_user_id,
    update_tenant_id = :update_tenant_id
WHERE id = :id AND status = 'pending'
""")


def _json_dump(value: Any) -> str | None:
    """JSON 列显式序列化：text() 不负责转换 Python 对象。"""
    return None if value is None else json.dumps(value, ensure_ascii=False)


class QaResultDao:
    """问答结果与 RAGAS 评估的读写。"""

    @staticmethod
    async def insert(*, record: dict[str, Any], audit: dict[str, Any]) -> str:
        """写一条问答结果，返回其 id。"""
        params = {**record, **audit}
        params["retrieved_contexts"] = _json_dump(params.get("retrieved_contexts"))
        params["sources"] = _json_dump(params.get("sources"))
        params["token_usage"] = _json_dump(params.get("token_usage"))
        params["extra"] = _json_dump(params.get("extra"))
        async with session_scope() as session:
            return str(await fetch_value(session, _INSERT, params))

    @staticmethod
    async def get(*, result_id: str, tenant_id: int) -> dict[str, Any] | None:
        """按 id + 租户取一条结果。"""
        async with session_scope() as session:
            return await fetch_one(session, _SELECT, {"id": result_id, "tenant_id": tenant_id})

    @staticmethod
    async def list_paged(
        *,
        tenant_id: int,
        session_id: str | None,
        status: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[dict[str, Any]], int]:
        """租户内分页列表（可按会话/状态过滤）。"""
        params = {"tenant_id": tenant_id, "session_id": session_id, "status": status}
        async with session_scope() as session:
            return await fetch_page(session, _LIST, _COUNT, params, page=page, page_size=page_size)

    @staticmethod
    async def update_reference(
        *,
        result_id: str,
        tenant_id: int,
        reference_answer: str,
        user_id: int,
        tenant_audit_id: int | None,
    ) -> int:
        """写入人工标准答案，返回受影响行数。"""
        async with session_scope() as session:
            result = await session.execute(
                _UPDATE_REFERENCE,
                {
                    "id": result_id,
                    "tenant_id": tenant_id,
                    "reference_answer": reference_answer,
                    "update_user_id": user_id,
                    "update_tenant_id": tenant_audit_id,
                },
            )
            return result.rowcount or 0

    @staticmethod
    async def list_evals(*, qa_result_id: str, tenant_id: int) -> list[dict[str, Any]]:
        """某条问答结果的 RAGAS 评估记录（按时间倒序）。"""
        async with session_scope() as session:
            return await fetch_all(
                session,
                _LIST_EVALS,
                {"qa_result_id": qa_result_id, "tenant_id": tenant_id},
            )

    @staticmethod
    async def insert_eval(*, eval_id: str, record: dict[str, Any], audit: dict[str, Any]) -> None:
        """创建一条 pending 评估记录（由接口触发，handler 消费后回填）。"""
        params = {"id": eval_id, **record, **audit}
        params["metrics"] = _json_dump(record.get("metrics"))
        async with session_scope() as session:
            await session.execute(_INSERT_EVAL, params)

    @staticmethod
    async def get_eval(eval_id: str) -> dict[str, Any] | None:
        """取评估记录状态（handler 幂等判断用）。"""
        async with session_scope() as session:
            return await fetch_one(session, _SELECT_EVAL, {"id": eval_id})

    @staticmethod
    async def finish_eval(
        *,
        eval_id: str,
        status: str,
        faithfulness: float | None = None,
        answer_relevancy: float | None = None,
        context_precision: float | None = None,
        context_recall: float | None = None,
        answer_correctness: float | None = None,
        metrics: dict[str, Any] | None = None,
        error_msg: str | None = None,
        eval_at: datetime | None = None,
        user_id: int | None = None,
        tenant_id: int | None = None,
    ) -> int:
        """回填评估结果（仅 pending 可更新，保证幂等）。"""
        async with session_scope() as session:
            result = await session.execute(
                _UPDATE_EVAL,
                {
                    "id": eval_id,
                    "status": status,
                    "faithfulness": faithfulness,
                    "answer_relevancy": answer_relevancy,
                    "context_precision": context_precision,
                    "context_recall": context_recall,
                    "answer_correctness": answer_correctness,
                    "metrics": _json_dump(metrics),
                    "error_msg": error_msg,
                    "eval_at": eval_at,
                    "update_user_id": user_id,
                    "update_tenant_id": tenant_id,
                },
            )
            return result.rowcount or 0
