"""RAGAS 官方质量评估（ragas 库 `evaluate` + 官方 metrics）。

与旧实现的区别：
- 旧：单次自研 prompt 让 LLM 一次性打 5 个分（不是 RAGAS 算法）；
- 新：使用 ragas 官方指标（Faithfulness / AnswerRelevancy / ContextPrecision /
  ContextRecall / AnswerCorrectness），由 ragas 内置 prompt 与计算逻辑产出分数，
  通过官方入口 `ragas.evaluate(...)` 执行；
- 评审模型复用项目 LLM（LangchainLLMWrapper），embeddings 复用已预加载的 BGE-M3。

为什么不用 collections（0.4 新 API）：
  新版 collections 指标要求 `llm_factory` + instructor 适配，而当前环境的
  `openai 2.x` 与 `instructor 1.x` 不兼容（instructor 初始化失败），因此使用
  `ragas.evaluate` + 官方 metrics（ragas 长期支持入口，算法与 prompt 均为官方实现）。

失败策略：任一指标计算失败即抛 `RagasEvalError`（不降级、不编造分数），
由 broker handler 记为 `failed` 并落库错误信息。
"""

from __future__ import annotations

import asyncio
from typing import Any, Sequence

from langchain_core.embeddings import Embeddings
from pydantic import BaseModel, Field

from backend.common.logger import logger


class RagasEvalError(RuntimeError):
    """RAGAS 评测失败（依赖缺失 / 模型不可用 / 指标计算异常）。"""


class RagasScores(BaseModel):
    """五项指标分数（0~1）；无检索上下文时 context 类指标为 None。"""

    faithfulness: float | None = Field(default=None, ge=0, le=1, description="回答是否由检索上下文支持")
    answer_relevancy: float | None = Field(default=None, ge=0, le=1, description="回答与问题的相关程度")
    context_precision: float | None = Field(default=None, ge=0, le=1, description="检索上下文的精确率")
    context_recall: float | None = Field(default=None, ge=0, le=1, description="检索上下文的召回率")
    answer_correctness: float | None = Field(default=None, ge=0, le=1, description="回答与标准答案的一致度")
    reason: str = Field(default="", description="评测说明（参与指标 / 失败原因）")


class _BgeEmbeddings(Embeddings):
    """把项目已预加载的 BGE-M3 适配为 LangChain Embeddings（ragas 内部使用）。"""

    def __init__(self, fn: Any) -> None:
        self._fn = fn

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        res = self._fn(list(texts))
        dense = res["dense"] if isinstance(res, dict) else res
        return [[float(x) for x in vec] for vec in dense]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


def _clip(value: Any) -> float:
    return round(max(0.0, min(1.0, float(value))), 4)


def _resolve_embeddings() -> Any:
    """复用运行中的 BGE-M3（ModelManager 预加载时挂在全局 embedding key）。"""
    from ragas.embeddings import LangchainEmbeddingsWrapper

    from backend.app_state import app_state

    factory = app_state.llm_factory
    fn = factory.get_cached("embedding") if factory is not None else None
    if fn is None:
        raise RagasEvalError("embedding 模型未就绪（ModelManager 未完成预加载）")
    return LangchainEmbeddingsWrapper(_BgeEmbeddings(fn))


def _run_evaluate(chat: Any, embeddings: Any, sample: Any, metrics: list) -> dict[str, float]:
    """同步执行官方 evaluate（在线程中调用，避免阻塞事件循环）。"""
    from ragas import EvaluationDataset, evaluate
    from ragas.llms import LangchainLLMWrapper
    from ragas.run_config import RunConfig

    dataset = EvaluationDataset(samples=[sample])
    result = evaluate(
        dataset=dataset,
        metrics=metrics,
        llm=LangchainLLMWrapper(chat),
        embeddings=embeddings,
        run_config=RunConfig(max_workers=2, timeout=180),
        raise_exceptions=True,  # 失败即抛出，不产出 NaN 分数
    )
    frame = result.to_pandas()
    if frame.empty:
        raise RagasEvalError("RAGAS 未返回评测结果")
    row = frame.iloc[0]
    out: dict[str, float] = {}
    for metric in metrics:
        name = str(getattr(metric, "name", "") or "")
        if name and name in frame.columns:
            value = row[name]
            if value is not None and not (isinstance(value, float) and value != value):
                out[name] = _clip(value)
    return out


async def evaluate_qa_result(
    *,
    question: str,
    answer: str,
    contexts: Sequence[str],
    reference_answer: str,
) -> RagasScores:
    """按 RAGAS 官方指标评测一条问答结果。

    - 无检索上下文时跳过 faithfulness / context_precision / context_recall；
    - 任一指标失败即抛 `RagasEvalError`（不降级、不返回猜测值）。
    """
    q = (question or "").strip()
    a = (answer or "").strip()
    ref = (reference_answer or "").strip()
    ctxs = [str(c).strip() for c in (contexts or []) if str(c or "").strip()]

    if not q or not a:
        raise RagasEvalError("问题或回答为空，无法评测")
    if not ref:
        raise RagasEvalError("缺少人工标准答案，无法评测")

    try:
        from ragas import SingleTurnSample
        from ragas.metrics import (
            answer_correctness,
            answer_relevancy,
            context_precision,
            context_recall,
            faithfulness,
        )
    except ImportError as exc:  # pragma: no cover - 依赖缺失
        raise RagasEvalError(f"ragas 未安装或版本不兼容：{exc}") from exc

    from backend.common.llm.llm_factory import get_llm

    chat = await get_llm("qa")
    embeddings = _resolve_embeddings()

    sample = SingleTurnSample(
        user_input=q,
        response=a,
        retrieved_contexts=ctxs or None,
        reference=ref,
    )

    metrics = [answer_relevancy, answer_correctness]
    if ctxs:
        metrics.extend([faithfulness, context_precision, context_recall])

    try:
        values = await asyncio.to_thread(_run_evaluate, chat, embeddings, sample, metrics)
    except RagasEvalError:
        raise
    except Exception as exc:  # noqa: BLE001 - 统一转为业务评测错误
        raise RagasEvalError(f"RAGAS 指标计算失败：{type(exc).__name__}: {exc}") from exc

    missing = [m for m in ("answer_relevancy", "answer_correctness") if m not in values]
    if missing:
        raise RagasEvalError(f"RAGAS 未产出必需指标：{', '.join(missing)}")

    logger.debug(f"ragas.eval.done | metrics={values} | contexts={len(ctxs)}")
    return RagasScores(
        faithfulness=values.get("faithfulness"),
        answer_relevancy=values.get("answer_relevancy"),
        context_precision=values.get("context_precision"),
        context_recall=values.get("context_recall"),
        answer_correctness=values.get("answer_correctness"),
        reason=f"ragas 官方指标（contexts={len(ctxs)}）",
    )
