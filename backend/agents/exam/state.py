"""试卷批改 State。"""
from __future__ import annotations

from typing import Dict, List, Optional, TypedDict


class ExamState(TypedDict, total=False):
    """批改图状态。三轨评分并行写入 grades，HITL 前挂起等待教师确认。"""

    tenant_id: str
    trace_id: str
    file_ref: str
    items: list                      # 题目元数据
    grades: Dict[str, dict]          # 客观/简答/代码三轨评分
    summary: str
    hitl_reason: str
    published: bool
    errors: List[str]
