"""智能问答 State。"""
from __future__ import annotations

from typing import List, Optional, TypedDict


class QAState(TypedDict, total=False):
    """问答图状态。intent 粗分、chunks 检索结果、confidence 决定兜底分支。"""

    tenant_id: str
    trace_id: str
    query: str
    intent: str
    chunks: List[dict]
    confidence: float
    answer: str
    errors: List[str]
