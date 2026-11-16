"""问答图路由函数：classify/retrieve/web_search 之后的分流（图装配由 AgentTemplate 统一完成）。"""

from __future__ import annotations

from backend.agents.qa.state import QAState


def _route_by_query_type(state: QAState) -> str:
    """classify_query 之后的路由：按 query_type 与 enable_web_search 分流。"""
    qt = state.get("query_type", "PRECISE").upper()
    if qt == "GENERAL" and state.get("enable_web_search", False):
        return "GENERAL_WEB"
    return qt


def _route_by_confidence(state: QAState) -> str:
    """retrieve 之后的路由：按置信度和联网开关分流。"""
    if state.get("is_high_confidence", False):
        return "high"
    if state.get("enable_web_search", False):
        return "low_web"
    return "low_direct"


def _route_after_web_search(state: QAState) -> str:
    """web_search 节点被两条路径共用，走完搜索后需要区分去向。"""
    if state.get("query_type", "").upper() == "GENERAL":
        return "generate_general"
    return "generate_direct"
