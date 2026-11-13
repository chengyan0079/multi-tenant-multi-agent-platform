"""问答结果接口：分页列表 / 详情 / RAGAS 测评与质量评估，按租户隔离。"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import uuid6
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from backend.broker.publish import enqueue_task
from backend.broker.types import TaskType
from backend.common.logger import logger
from backend.common.response import success
from backend.data.dao.business.qa_result_dao import QaResultDao
from backend.middleware.auth import CurrentUser, get_current_user
from backend.security.rbac import Scope
from backend.security.security import require_scope

router = APIRouter(prefix="/qa/results", tags=["qa-results"])


class ReviewIn(BaseModel):
    """测评请求：人工标准答案（必填），评估模型与数据集版本可选。"""

    reference_answer: str = Field(..., min_length=1, max_length=8000)
    evaluator_model: str | None = Field(None, max_length=64, description="评估用 LLM 标识，缺省取 qa-default")
    dataset_version: str | None = Field(None, max_length=32, description="数据集版本，缺省 v1")


def _json_value(value: Any) -> Any:
    """JSON 列经 text() 取回可能是字符串，这里兜底解析。"""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _iso(value: Any) -> str | None:
    return value.isoformat() if value else None


def _tenant_id(current: CurrentUser) -> int:
    if current.tenant_id is None:
        raise HTTPException(status_code=403, detail="缺少租户上下文")
    return current.tenant_id


def _detail(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "trace_id": row.get("trace_id"),
        "tenant_id": row.get("tenant_id"),
        "user_id": row.get("user_id"),
        "session_id": row.get("session_id"),
        "thread_id": str(row["thread_id"]) if row.get("thread_id") else None,
        "agent_type": row.get("agent_type"),
        "question": row.get("question"),
        "answer": row.get("answer"),
        "answer_mode": row.get("answer_mode"),
        "query_type": row.get("query_type"),
        "confidence": float(row["confidence"]) if row.get("confidence") is not None else None,
        "retrieved_contexts": _json_value(row.get("retrieved_contexts")),
        "sources": _json_value(row.get("sources")),
        "reference_answer": row.get("reference_answer"),
        "latency_ms": row.get("latency_ms"),
        "token_usage": _json_value(row.get("token_usage")),
        "enable_web_search": row.get("enable_web_search"),
        "status": row.get("status"),
        "error_msg": row.get("error_msg"),
        "extra": _json_value(row.get("extra")),
        "created_at": _iso(row.get("create_at")),
        "updated_at": _iso(row.get("updated_at")),
    }


@router.get("", summary="问答结果列表（分页）")
async def list_results(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    session_id: str | None = Query(None, description="按会话过滤"),
    result_status: str | None = Query(None, alias="status", description="按执行状态过滤"),
    _: object = Depends(require_scope(Scope.QA_RESULT_PAGE)),  # noqa: B008
    current: CurrentUser = Depends(get_current_user),
) -> Any:
    """分页查询问答结果。

    请求：query { page, page_size, session_id?, status? }
    权限：qa_result:page
    返回：items / total / page / page_size
    """
    tenant_id = _tenant_id(current)
    rows, total = await QaResultDao.list_paged(
        tenant_id=tenant_id,
        session_id=session_id,
        status=result_status,
        page=page,
        page_size=page_size,
    )
    items = [
        {
            "id": str(r["id"]),
            "trace_id": r.get("trace_id"),
            "tenant_id": r.get("tenant_id"),
            "user_id": r.get("user_id"),
            "session_id": r.get("session_id"),
            "question": r.get("question"),
            "answer_mode": r.get("answer_mode"),
            "query_type": r.get("query_type"),
            "confidence": float(r["confidence"]) if r.get("confidence") is not None else None,
            "status": r.get("status"),
            "latency_ms": r.get("latency_ms"),
            "created_at": _iso(r.get("create_at")),
        }
        for r in rows
    ]
    return success({"items": items, "total": total, "page": page, "page_size": page_size})


@router.get("/{result_id}", summary="问答结果详情")
async def get_result(
    result_id: str,
    _: object = Depends(require_scope(Scope.QA_RESULT_VIEW)),  # noqa: B008
    current: CurrentUser = Depends(get_current_user),
) -> Any:
    """获取单条问答结果详情。

    请求：path { result_id }
    权限：qa_result:view
    返回：完整结果视图（含上下文、来源、token 用量等）
    """
    row = await QaResultDao.get(result_id=result_id, tenant_id=_tenant_id(current))
    if row is None:
        raise HTTPException(status_code=404, detail="问答结果不存在")
    return success(_detail(row))


@router.post(
    "/{result_id}/review", status_code=status.HTTP_202_ACCEPTED, summary="结果测评（触发 RAGAS）"
)
async def submit_review(
    result_id: str,
    body: ReviewIn,
    _: object = Depends(require_scope(Scope.QA_RESULT_REVIEW)),  # noqa: B008
    current: CurrentUser = Depends(get_current_user),
) -> Any:
    """写入人工标准答案并触发 RAGAS 异步测评。

    说明：创建 pending 评估记录，投递 QA_RAGAS_REVIEW 消息；入队失败标记 failed 避免永久 pending。
    请求：path { result_id }, body { reference_answer: str 必填 }
    权限：qa_result:review
    返回：{ eval_id, status }
    """
    tenant_id = _tenant_id(current)
    reference_answer = body.reference_answer.strip()
    if not reference_answer:
        raise HTTPException(status_code=400, detail="人工标准答案不能为空")

    row = await QaResultDao.get(result_id=result_id, tenant_id=tenant_id)
    if row is None:
        raise HTTPException(status_code=404, detail="问答结果不存在")

    updated = await QaResultDao.update_reference(
        result_id=result_id,
        tenant_id=tenant_id,
        reference_answer=reference_answer,
        user_id=current.user_id,
        tenant_audit_id=current.home_tenant_id or tenant_id,
    )
    if updated == 0:
        raise HTTPException(status_code=404, detail="问答结果不存在")

    eval_id = str(uuid6.uuid7())
    await QaResultDao.insert_eval(
        eval_id=eval_id,
        record={
            "qa_result_id": result_id,
            "trace_id": row.get("trace_id"),
            "tenant_id": tenant_id,
            "evaluator": "llm",
            "evaluator_model": (body.evaluator_model or "qa-default")[:64],
            "dataset_version": (body.dataset_version or "v1")[:32],
            "metrics": None,
            "status": "pending",
            "error_msg": None,
            "eval_at": datetime.now(),
        },
        audit={
            "create_user_id": current.user_id,
            "update_user_id": current.user_id,
            "create_tenant_id": current.home_tenant_id or tenant_id,
            "update_tenant_id": current.home_tenant_id or tenant_id,
        },
    )
    # 测评状态落在 agent_qa_ragas_evals；列表页若需展示
    #  “是否已测评/最近得分”，需回写 agent_qa_results 或按 qa_result_id 聚合查询。
    try:
        key = await enqueue_task(
            TaskType.QA_RAGAS_REVIEW,
            tenant_id=tenant_id,
            user_id=current.user_id,
            data={"eval_id": eval_id, "qa_result_id": result_id},
        )
    except Exception as exc:  # noqa: BLE001 - 入队异常按失败处理，避免 eval 永久 pending
        logger.exception(f"qa_ragas.enqueue_failed eval={eval_id}: {exc}")
        key = None
    if key is None:
        # 入队失败（broker 未启用 / Outbox 写入失败）：标记 failed，避免前端一直看到 pending
        await QaResultDao.finish_eval(
            eval_id=eval_id,
            status="failed",
            error_msg="RAGAS 任务入队失败",
            eval_at=datetime.now(),
            user_id=current.user_id,
            tenant_id=tenant_id,
        )
        raise HTTPException(status_code=503, detail="测评任务入队失败，请稍后重试")
    return success({"eval_id": eval_id, "status": "pending"})


@router.get("/{result_id}/quality", summary="结果质量（RAGAS 评估记录）")
async def get_quality(
    result_id: str,
    _: object = Depends(require_scope(Scope.QA_RESULT_REVIEW)),  # noqa: B008
    current: CurrentUser = Depends(get_current_user),
) -> Any:
    """查询某结果的 RAGAS 质量评估记录。

    请求：path { result_id }
    权限：qa_result:review
    返回：items[{ faithfulness, answer_relevancy, context_precision, ... }]
    """
    tenant_id = _tenant_id(current)
    row = await QaResultDao.get(result_id=result_id, tenant_id=tenant_id)
    if row is None:
        raise HTTPException(status_code=404, detail="问答结果不存在")

    rows = await QaResultDao.list_evals(qa_result_id=result_id, tenant_id=tenant_id)
    items = [
        {
            "id": str(r["id"]),
            "qa_result_id": str(r["qa_result_id"]),
            "trace_id": r.get("trace_id"),
            "tenant_id": r.get("tenant_id"),
            "evaluator": r.get("evaluator"),
            "evaluator_model": r.get("evaluator_model"),
            "dataset_version": r.get("dataset_version"),
            "faithfulness": float(r["faithfulness"]) if r.get("faithfulness") is not None else None,
            "answer_relevancy": float(r["answer_relevancy"])
            if r.get("answer_relevancy") is not None
            else None,
            "context_precision": float(r["context_precision"])
            if r.get("context_precision") is not None
            else None,
            "context_recall": float(r["context_recall"])
            if r.get("context_recall") is not None
            else None,
            "answer_correctness": float(r["answer_correctness"])
            if r.get("answer_correctness") is not None
            else None,
            "metrics": _json_value(r.get("metrics")),
            "status": r.get("status"),
            "error_msg": r.get("error_msg"),
            "eval_at": _iso(r.get("eval_at")),
            "created_at": _iso(r.get("create_at")),
            "updated_at": _iso(r.get("updated_at")),
        }
        for r in rows
    ]
    return success({"items": items})
