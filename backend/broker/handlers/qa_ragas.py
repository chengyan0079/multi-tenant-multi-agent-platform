"""问答 RAGAS 测评 handler（消费 qa.ragas_review）：仅 status='pending' 执行，失败交框架重试。"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from backend.agents.qa.ragas_eval import evaluate_qa_result
from backend.broker.envelope import TaskMessage
from backend.broker.security import authorize_task
from backend.common.logger import logger
from backend.data.dao.business.qa_result_dao import QaResultDao
from backend.security.rbac import Scope

# 重试到该次数仍未成功则标记 failed（框架随后仍会重投一次，但因非 pending 直接跳过）
_MARK_FAILED_AT_RETRY = 2


def _parse_json(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


async def handle_qa_ragas_review(msg: TaskMessage) -> None:
    # 零信任：消费端重校验 qa_result:review（该权限点仅租户用户持有）
    await authorize_task(msg.header.user_id, msg.header.tenant_id, [Scope.QA_RESULT_REVIEW])

    data = msg.data
    eval_id = data.get("eval_id")
    qa_result_id = data.get("qa_result_id")
    if not eval_id or not qa_result_id:
        logger.warning("[qa.ragas_review] 缺少 eval_id/qa_result_id，丢弃")
        return

    tenant_id = int(msg.header.tenant_id)  # authorize_task 已保证非空

    row = await QaResultDao.get_eval(str(eval_id))
    if row is None or row["status"] != "pending":
        logger.info(f"[qa.ragas_review] 跳过 eval={eval_id}（不存在或已处理）")
        return

    result = await QaResultDao.get(result_id=str(qa_result_id), tenant_id=tenant_id)
    if result is None:
        await QaResultDao.finish_eval(
            eval_id=str(eval_id),
            status="failed",
            error_msg="问答结果不存在",
            eval_at=datetime.now(),
            user_id=msg.header.user_id,
            tenant_id=tenant_id,
        )
        return

    contexts = _parse_json(result.get("retrieved_contexts")) or []
    context_texts = [str(c.get("content", "")) for c in contexts if isinstance(c, dict)]
    try:
        scores = await evaluate_qa_result(
            question=str(result.get("question") or ""),
            answer=str(result.get("answer") or ""),
            contexts=context_texts,
            reference_answer=str(result.get("reference_answer") or ""),
        )
    except Exception as exc:  # noqa: BLE001 - 交由框架重试/死信
        logger.exception(f"[qa.ragas_review] 评估失败 eval={eval_id}: {exc}")
        if msg.header.retry_count >= _MARK_FAILED_AT_RETRY:
            await QaResultDao.finish_eval(
                eval_id=str(eval_id),
                status="failed",
                error_msg=str(exc)[:2000],
                eval_at=datetime.now(),
                user_id=msg.header.user_id,
                tenant_id=tenant_id,
            )
        raise

    await QaResultDao.finish_eval(
        eval_id=str(eval_id),
        status="success",
        faithfulness=scores.faithfulness,
        answer_relevancy=scores.answer_relevancy,
        context_precision=scores.context_precision,
        context_recall=scores.context_recall,
        answer_correctness=scores.answer_correctness,
        metrics=scores.model_dump(),
        eval_at=datetime.now(),
        user_id=msg.header.user_id,
        tenant_id=tenant_id,
    )
    logger.info(f"[qa.ragas_review] 完成 eval={eval_id} qa_result={qa_result_id}")
