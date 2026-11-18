"""slow_sql_explain 工具：基于执行计划/元数据做慢 SQL 纯分析，**不连接数据库**。

输入由调用方提供（db_metadata / explain 已取到的 plan、metadata、sql），
本工具只做规则判定与建议，不发起任何 DB 连接。
"""

from __future__ import annotations

from typing import Any

from backend.tools.protocol import BaseTool

_SLOW_SCAN = {"ALL", "index", "full"}
_BAD_FEATURES = ("Using temporary", "Using filesort", "Using join buffer")


class SlowSqlExplainTool(BaseTool):
    """慢 SQL —— 纯分析（不连库）。"""

    name = "slow_sql_explain"
    description = "基于执行计划/元数据分析是否慢 SQL 并给优化建议（不连接数据库）"

    async def run(self, **kwargs: Any) -> dict:
        sql = str(kwargs.get("sql") or kwargs.get("sql_text") or "")
        plan_text = str(kwargs.get("plan") or kwargs.get("plan_text") or "")
        metadata = kwargs.get("metadata") or {}

        issues: list[str] = []
        suggestions: list[str] = []
        upper = plan_text.upper()

        if "FULL SCAN" in upper or "SEQ SCAN" in upper or '"NODE TYPE": "SEQ SCAN"' in upper:
            issues.append("检测到全表扫描")
            suggestions.append("为过滤/排序/连接列补充合适索引，避免全表扫描")
        if "USING TEMPORARY" in upper:
            issues.append("使用临时表")
            suggestions.append("优化 GROUP BY/ORDER BY，减少临时表")
        if "USING FILESORT" in upper:
            issues.append("文件排序")
            suggestions.append("让 ORDER BY 走索引，避免 filesort")
        if "ROWS EXAMINED" in upper and "ROWS RETURNED" in upper:
            issues.append("扫描行数/返回行数比例可能偏高")
            suggestions.append("减少扫描行：加索引或缩小 WHERE 范围")
        if sql.strip().upper().startswith("SELECT *"):
            issues.append("SELECT * 取全列")
            suggestions.append("只取必要列，减少 IO 与网络传输")
        if "LIMIT" in sql.upper() and ("OFFSET" in sql.upper() or "," in sql):
            issues.append("深分页")
            suggestions.append("深分页改用游标/基于上次最大主键分页")

        col_count = len(metadata.get("columns") or [])
        idx_count = len(metadata.get("indexes") or [])
        if col_count and idx_count == 0:
            suggestions.append("目标表无索引，建议按查询条件建立索引")

        is_slow = bool(issues)
        return {
            "is_slow": is_slow,
            "issues": issues,
            "suggestions": suggestions,
            "confidence": 0.6 if plan_text else 0.3,
            "note": "未提供执行计划，结论仅供参考" if not plan_text else "",
        }
