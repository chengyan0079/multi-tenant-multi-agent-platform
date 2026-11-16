"""问答结果 DAO（阶段2）：**以 agent_unified_turn 为唯一历史源**。

- 列表/详情直接读 `agent_unified_turn`（agent_type='qa'），不再有 agent_qa_results；
- RAGAS 评测存 `agent_qa_ragas_evals`，外键为 `turn_id`；
- 评测必须人工补充标准答案（reference_answer）后才会写 pending 记录并执行。
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import text

from backend.data.sql import (
    execute_write,
    fetch_all,
    fetch_one,
    fetch_page,
    fetch_value,
    session_scope,
)

_QA_WHERE = (
    "WHERE t.tenant_id = :tenant_id AND t.agent_type = 'qa' "
    "AND (CAST(:session_id AS UUID) IS NULL OR t.thread_id = CAST(:session_id AS UUID)) "
    "AND (CAST(:status AS VARCHAR) IS NULL OR t.status = :status)"
)

_QA_COLUMNS = """
       t.id, t.trace_id, t.tenant_id, t.user_id, t.agent_type,
       t.user_content AS question, t.assistant_content AS answer,
       t.payload->>'answer_mode' AS answer_mode,
       t.payload->>'query_type' AS query_type,
       (t.payload->>'confidence')::numeric AS confidence,
       t.payload->'retrieved_contexts' AS retrieved_contexts,
       t.payload->'sources' AS sources,
       t.latency_ms, t.token_usage, t.status, t.error_code AS error_msg,
       t.payload AS extra, t.create_at, t.updated_at,
       t.thread_id::text AS session_id, t.thread_id::text AS thread_id
"""

_LIST = text(
    f"SELECT {_QA_COLUMNS} FROM agent_unified_turn t {_QA_WHERE} "
    "ORDER BY t.create_at DESC LIMIT :limit OFFSET :offset"
)

_COUNT = text(f"SELECT count(*) FROM agent_unified_turn t {_QA_WHERE}")

_GET = text(
    f"SELECT {_QA_COLUMNS} FROM agent_unified_turn t "
    "WHERE t.id = CAST(:id AS UUID) AND t.tenant_id = :tenant_id AND t.agent_type = 'qa'"
)

_INSERT_EVAL = text("""
INSERT INTO agent_qa_ragas_evals (
    id, turn_id, trace_id, tenant_id, evaluator, evaluator_model, dataset_version,
    reference_answer, retrieved_contexts, metrics, status, error_msg, eval_at,
    create_user_id, update_user_id, create_tenant_id, update_tenant_id
) VALUES (
    :id, CAST(:turn_id AS UUID), :trace_id, :tenant_id, :evaluator, :evaluator_model, :dataset_version,
    :reference_answer, CAST(:retrieved_contexts AS JSONB), CAST(:metrics AS JSONB), :status, :error_msg, :eval_at,
    :create_user_id, :update_user_id, :create_tenant_id, :update_tenant_id
)
RETURNING id
""")

_SELECT_EVAL = text("""
SELECT id, turn_id, trace_id, tenant_id, evaluator, evaluator_model, dataset_version,
       reference_answer, retrieved_contexts,
       faithfulness, answer_relevancy, context_precision, context_recall, answer_correctness,
       metrics, status, error_msg, eval_at, create_at, updated_at
FROM agent_qa_ragas_evals WHERE id = CAST(:id AS UUID)
""")

_LIST_EVALS = text("""
SELECT id, turn_id, trace_id, tenant_id, evaluator, evaluator_model, dataset_version,
       reference_answer, retrieved_contexts,
       faithfulness, answer_relevancy, context_precision, context_recall, answer_correctness,
       metrics, status, error_msg, eval_at, create_at, updated_at
FROM agent_qa_ragas_evals
WHERE turn_id = CAST(:turn_id AS UUID) AND tenant_id = :tenant_id
ORDER BY create_at DESC
""")

_FINISH_EVAL = text("""
UPDATE agent_qa_ragas_evals
SET status = :status,
    error_msg = :error_msg,
    faithfulness = :faithfulness,
    answer_relevancy = :answer_relevancy,
    context_precision = :context_precision,
    context_recall = :context_recall,
    answer_correctness = :answer_correctness,
    metrics = CAST(:metrics AS JSONB),
    eval_at = :eval_at,
    update_user_id = :update_user_id,
    update_tenant_id = :update_tenant_id
WHERE id = CAST(:id AS UUID)
""")


def _json_dump(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return None


class QaResultDao:
    """问答结果（turn 视图）+ RAGAS 评测读写。"""

    # ---------- 问答结果（读 agent_unified_turn） ----------

    @staticmethod
    async def list_paged(
        *,
        tenant_id: int,
        session_id: str | None = None,
        status: str | None = None,
        page: int = 1,
        page_size: int = 20,
        turn_id: str | None = None,
        thread_id: str | None = None,
        trace_id: str | None = None,
        user_id: int | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        """按 id / thread_id / trace_id / user_id / 会话 / 状态 过滤（模糊匹配 UUID 片段）。"""
        conds = ["t.tenant_id = :tenant_id", "t.agent_type = 'qa'"]
        params: dict[str, Any] = {
            "tenant_id": tenant_id,
            "limit": page_size,
            "offset": max(page - 1, 0) * page_size,
        }
        if session_id:
            conds.append("t.thread_id = CAST(:session_id AS UUID)")
            params["session_id"] = session_id
        if status:
            conds.append("t.status = :status")
            params["status"] = status
        if turn_id:
            conds.append("CAST(t.id AS text) ILIKE :turn_like")
            params["turn_like"] = f"%{turn_id.strip()}%"
        if thread_id:
            conds.append("CAST(t.thread_id AS text) ILIKE :thr_like")
            params["thr_like"] = f"%{thread_id.strip()}%"
        if trace_id:
            conds.append("t.trace_id ILIKE :trace_like")
            params["trace_like"] = f"%{trace_id.strip()}%"
        if user_id is not None:
            conds.append("t.user_id = :user_id")
            params["user_id"] = user_id
        where = " WHERE " + " AND ".join(conds)
        list_sql = text(
            f"SELECT {_QA_COLUMNS} FROM agent_unified_turn t{where} "
            "ORDER BY t.create_at DESC LIMIT :limit OFFSET :offset"
        )
        count_sql = text(f"SELECT count(*) FROM agent_unified_turn t{where}")
        async with session_scope() as session:
            total = await fetch_value(session, count_sql, params)
            rows = await fetch_all(session, list_sql, params)
        return [dict(r) for r in rows], int(total or 0)

    @staticmethod
    async def get(*, result_id: str, tenant_id: int) -> dict[str, Any] | None:
        """result_id 即 agent_unified_turn.id。"""
        async with session_scope() as session:
            return await fetch_one(session, _GET, {"id": result_id, "tenant_id": tenant_id})

    # ---------- RAGAS 评测 ----------

    @staticmethod
    async def insert_eval(*, eval_id: str, record: dict[str, Any], audit: dict[str, Any]) -> None:
        """创建 pending 评测（record.turn_id 为评测对象，reference_answer 必填）。"""
        params = {
            "id": eval_id,
            "turn_id": record.get("turn_id"),
            "trace_id": record.get("trace_id"),
            "tenant_id": record.get("tenant_id"),
            "evaluator": record.get("evaluator") or "ragas",
            "evaluator_model": record.get("evaluator_model"),
            "dataset_version": record.get("dataset_version"),
            "reference_answer": record.get("reference_answer"),
            "retrieved_contexts": _json_dump(record.get("retrieved_contexts")),
            "metrics": _json_dump(record.get("metrics")),
            "status": record.get("status") or "pending",
            "error_msg": record.get("error_msg"),
            "eval_at": record.get("eval_at") or datetime.now(),
            **audit,
        }
        async with session_scope() as session:
            await fetch_value(session, _INSERT_EVAL, params)

    @staticmethod
    async def get_eval(eval_id: str) -> dict[str, Any] | None:
        async with session_scope() as session:
            return await fetch_one(session, _SELECT_EVAL, {"id": eval_id})

    @staticmethod
    async def list_evals(*, turn_id: str, tenant_id: int) -> list[dict[str, Any]]:
        async with session_scope() as session:
            return await fetch_all(session, _LIST_EVALS, {"turn_id": turn_id, "tenant_id": tenant_id})

    @staticmethod
    async def finish_eval(
        *,
        eval_id: str,
        status: str,
        error_msg: str | None = None,
        eval_at: datetime | None = None,
        user_id: int | None = None,
        tenant_id: int | None = None,
        faithfulness: float | None = None,
        answer_relevancy: float | None = None,
        context_precision: float | None = None,
        context_recall: float | None = None,
        answer_correctness: float | None = None,
        metrics: dict | None = None,
    ) -> None:
        async with session_scope() as session:
            await execute_write(
                session,
                _FINISH_EVAL,
                {
                    "id": eval_id,
                    "status": status,
                    "error_msg": error_msg,
                    "eval_at": eval_at or datetime.now(),
                    "update_user_id": user_id,
                    "update_tenant_id": tenant_id,
                    "faithfulness": faithfulness,
                    "answer_relevancy": answer_relevancy,
                    "context_precision": context_precision,
                    "context_recall": context_recall,
                    "answer_correctness": answer_correctness,
                    "metrics": _json_dump(metrics),
                },
            )
            await session.commit()
