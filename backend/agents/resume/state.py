"""简历审查 State：节点间共享的数据结构。"""
from __future__ import annotations

from typing import Dict, List, Optional, TypedDict


class ResumeState(TypedDict, total=False):
    """简历审查图状态。tenant_id/trace_id 全链路透传，results 累积各维度评分。"""

    tenant_id: str
    trace_id: str
    file_ref: str                 # 上传后的简历引用（PDF）
    structured: dict              # 结构化提取结果
    scores: Dict[str, float]      # 六维度评分（并行写入）
    diagnosis: str                # 问题诊断
    report: str                   # 整体评价/报告
    errors: List[str]
