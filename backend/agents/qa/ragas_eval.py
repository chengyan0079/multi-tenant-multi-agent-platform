"""RAGAS 质量评估（自定义 LLM 打分，不依赖 ragas 库）。

按 RAGAS 五项指标定义构造评分 Prompt，用现有结构化 LLM 输出 0~1 分数：
faithfulness / answer_relevancy / context_precision / context_recall / answer_correctness。
"""
from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from backend.common.llm.llm_factory import get_structured_llm


class RagasScores(BaseModel):
    """五项指标分数（0~1）。"""

    faithfulness: float = Field(ge=0, le=1, description="回答是否完全由检索上下文支持")
    answer_relevancy: float = Field(ge=0, le=1, description="回答与问题的相关程度")
    context_precision: float = Field(ge=0, le=1, description="检索上下文中与问题相关的比例")
    context_recall: float = Field(ge=0, le=1, description="参考答案所需信息被上下文覆盖的比例")
    answer_correctness: float = Field(ge=0, le=1, description="回答与人工标准答案的一致程度")
    reason: str = Field(default="", description="简要评分理由")


_SYSTEM = """你是严谨的 RAG 问答质量评估器。依据给定材料，对模型回答按 RAGAS 五项指标打分（0~1）：
1. faithfulness：回答中的每个事实是否都能在检索上下文中找到依据（无依据/编造扣分）。
2. answer_relevancy：回答是否切题、直接回应问题（跑题/答非所问扣分）。
3. context_precision：检索上下文中与问题相关的内容占比（噪声越多分越低）。
4. context_recall：人工标准答案所需的关键信息是否被检索上下文覆盖。
5. answer_correctness：回答与人工标准答案在事实与结论上的一致程度。
只评价，不要改写回答；分数与理由必须基于材料。"""

_USER = """【问题】
{question}

【模型回答】
{answer}

【检索上下文】
{contexts}

【人工标准答案】
{reference}"""


def _truncate(text: str, limit: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[:limit] + "…"


async def evaluate_qa_result(
    *, question: str, answer: str, contexts: list[str], reference_answer: str
) -> RagasScores:
    """对一条问答结果做 RAGAS 五项指标打分。"""
    ctx_text = "\n---\n".join(
        f"[{i + 1}] {c}" for i, c in enumerate(contexts) if (c or "").strip()
    ) or "（无检索上下文）"
    prompt = _USER.format(
        question=_truncate(question, 2000),
        answer=_truncate(answer, 4000),
        contexts=_truncate(ctx_text, 6000),
        reference=_truncate(reference_answer, 4000),
    )
    structured_llm = await get_structured_llm("qa", RagasScores)
    return await structured_llm.ainvoke(
        [SystemMessage(content=_SYSTEM), HumanMessage(content=prompt)]
    )
