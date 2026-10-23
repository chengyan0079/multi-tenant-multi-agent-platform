"""模拟面试 State。"""
from __future__ import annotations

from typing import Dict, List, Optional, TypedDict


class InterviewState(TypedDict, total=False):
    """面试图状态。stage 推进状态机，history 累积问答，quality 评估中间结果。"""

    tenant_id: str
    trace_id: str
    session_id: str
    stage: str                     # init / question / evaluate / report / done
    candidate_answer: str
    history: List[dict]
    quality: float
    report: str
    errors: List[str]
