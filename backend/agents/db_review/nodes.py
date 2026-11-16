"""db_review 节点：加载变更单 → 方言校验 → 元数据预检 → 慢SQL分析 → 风险分级 → 优化建议 → 落库。"""

from __future__ import annotations

import json
import re

from langgraph.types import Send
from typing import Any

from sqlalchemy import text

from backend.agents.db_review.prompts import GRADE_PROMPT, SUGGEST_PROMPT
from backend.agents.db_review.state import DbReviewState
from backend.app_state import app_state
from backend.common.llm.llm_factory import get_llm
from backend.common.logger import get_logger
from backend.data.sql import fetch_value, session_scope
from backend.services.sql_script_service import (
    analyze_sql,
    normalize_db_type,
    parse_sql,
    validate_script,
)

logger = get_logger("db_review_nodes")

AGENT_TYPE = "db_review"
DB_TYPES = {"mysql", "postgresql"}


async def load_node(state: DbReviewState) -> dict:
    """校验输入并创建/复用变更单。"""
    sql_text = (state.get("sql_text") or state.get("query") or "").strip()
    db_type = normalize_db_type(state.get("db_type") or "")
    errors: list[str] = []
    if not sql_text:
        errors.append("缺少 SQL 脚本或长字符串")
    if db_type not in DB_TYPES:
        errors.append(f"不支持或缺少 db_type: {db_type}")
    check = validate_script(sql_text, db_type) if sql_text else {"errors": [], "warnings": []}
    errors.extend(check.get("errors") or [])
    if sql_text and db_type in DB_TYPES:
        errors.extend((parse_sql(sql_text, db_type).get("errors")) or [])
    if errors:
        return {"answer": "；".join(errors), "risk_level": None}

    tenant_id = int(state.get("tenant_id") or 0)
    user_id = int(state.get("user_id") or 0)
    async with session_scope() as session:
        request_id = await fetch_value(
            session,
            text(
                "INSERT INTO agent_change_request "
                "(tenant_id, user_id, thread_id, turn_id, title, target_database, db_type, "
                " connection_id, sql_text, script_file_id, drill_file_id, status, trace_id) "
                "VALUES (:tenant_id,:user_id,:thread_id,:turn_id,:title,:target_database,:db_type,"
                " :connection_id,:sql_text,:script_file_id,:drill_file_id,'reviewing',:trace_id) "
                "RETURNING id"
            ),
            {
                "tenant_id": tenant_id,
                "user_id": user_id,
                "thread_id": str(state.get("session_id") or state.get("thread_id") or ""),
                "turn_id": str(state.get("turn_id") or ""),
                "title": (state.get("query") or "")[:200],
                "target_database": state.get("target_database") or "",
                "db_type": db_type,
                "connection_id": state.get("connection_id") or "",
                "sql_text": sql_text,
                "script_file_id": state.get("script_file_id"),
                "drill_file_id": state.get("drill_file_id"),
                "trace_id": state.get("trace_id"),
            },
        )
    # 工具校验：该租户下且 enabled，否则结束并保存（前端提示）
    reg = getattr(app_state, "plugin_registry", None)
    required = ("db_metadata", "slow_sql_explain")
    missing = [
        n
        for n in required
        if reg is not None and not reg.is_tool_enabled_for_tenant(tenant_id, n)
    ]
    if missing:
        return {
            "request_id": int(request_id or 0),
            "tool_blocked": True,
            "answer": f"工具未在该租户启用：{'、'.join(missing)}，请先在「工具管理」绑定并启用",
        }

    return {
        "request_id": int(request_id or 0),
        "sql_text": sql_text,
        "db_type": db_type,
        "target_tables": list(state.get("target_tables") or []),
    }


async def fetch_metadata_node(state: DbReviewState) -> dict:
    """按 connection_id 调 db_metadata 工具取元数据（图内同一连接）。"""
    try:
        reg = getattr(app_state, "plugin_registry", None)
        if reg is None:
            return {"metadata": {"ok": False, "error": "工具注册表未就绪"}}
        meta = await reg.call(
            "db_metadata",
            tenant_id=int(state.get("tenant_id") or 0),
            connection_id=state.get("connection_id") or "",
            target_tables=list(state.get("target_tables") or []),
        )
    except Exception as exc:  # noqa: BLE001 - 降级
        logger.warning(f"db_metadata 失败: {exc}")
        meta = {"ok": False, "error": str(exc)}
    return {"metadata": meta}


_WHERE_TRUE_RE = re.compile(
    r"where\s+(?:1\s*=\s*1|true|'[^']*'\s*=\s*'[^']*'|(\w+)\s*=\s*\1)(?:\s|$|--|/\*)",
    re.I,
)


def _where_always_true(sql: str) -> bool:
    """检测 WHERE 恒真（1=1 / true / 'a'='a' / 同名列=列），视为无有效过滤条件。"""
    return bool(_WHERE_TRUE_RE.search(sql or ""))


async def analyze_node(state: DbReviewState) -> dict:
    """慢SQL + 元数据规则分析。"""
    metadata = state.get("metadata") or {}
    try:
        reg = getattr(app_state, "plugin_registry", None)
        slow = (
            await reg.call(
                "slow_sql_explain",
                sql=state.get("sql_text") or "",
                plan="",
                metadata=metadata,
            )
            if reg is not None
            else {}
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"slow_sql_explain 失败: {exc}")
        slow = {"is_slow": False, "issues": [], "suggestions": []}

    sql_text = state.get("sql_text") or ""
    sql_upper = sql_text.upper()
    head = sql_text.lstrip().split(None, 1)[0].upper() if sql_text.strip() else ""
    is_write_dml = head in ("UPDATE", "DELETE")
    has_where = bool(re.search(r"\bWHERE\b", sql_upper))
    where_true = _where_always_true(sql_text)
    rows = metadata.get("stats") or []
    est_rows = max((int(r.get("est_rows") or 0) for r in rows), default=0)
    dimensions = {
        "is_ddl": head in ("CREATE", "ALTER", "DROP", "TRUNCATE", "RENAME", "COMMENT"),
        "has_drop": "DROP" in sql_upper or "TRUNCATE" in sql_upper,
        "no_where_dml": is_write_dml and not has_where,
        "where_always_true": where_true,
        "estimated_rows": est_rows,
        "cross_db": False,
        "core_path": False,
    }
    return {"slow_sql": slow, "dimensions": dimensions}


def _parse_json(text_in: str) -> dict:
    """从 LLM 输出抽取 JSON（容错 ``` 包裹）。"""
    s = (text_in or "").strip()
    if s.startswith("```"):
        s = s.strip("`")
        if s.lower().startswith("json"):
            s = s[4:]
    try:
        return json.loads(s)
    except Exception:  # noqa: BLE001
        return {}




# --------------------------------------------------------------------------- #
# 并行预检：Send 扇出 → 各分支 → aggregate fan-in
# --------------------------------------------------------------------------- #
def fanout_prechecks(state: DbReviewState) -> list:
    """fetch 之后并行扇出 4 路预检。"""
    return [
        Send("pre_lock", state),
        Send("pre_rows", state),
        Send("pre_slow", state),
        Send("pre_meta", state),
    ]


def _extract_plan_rows(plan: object) -> int:
    """从 EXPLAIN 计划提取影响/扫描行数（PG Plan Rows / MySQL rows_examined_per_scan）。"""
    text = json.dumps(plan or [], ensure_ascii=False)
    for pat in (r'"Plan Rows":\s*(\d+)', r'"rows_examined_per_scan":\s*(\d+)'):
        m = re.search(pat, text)
        if m:
            return int(m.group(1))
    return 0


async def pre_lock_node(state: DbReviewState) -> dict:
    """锁/影响估算（基于 sqlglot 类型，方言无关）：query/dml 走 EXPLAIN 取行数；DDL 用元数据行数。"""
    sql = state.get("sql_text") or ""
    info = analyze_sql(sql, state.get("db_type") or "")
    kind = info.get("kind")
    lock_ms: int | None = None
    plan_ok = False
    plan_rows = 0
    if kind in ("query", "dml"):
        try:
            from backend.services.db_connection_service import explain

            r = await explain(
                int(state.get("tenant_id") or 0),
                state.get("connection_id") or "",
                sql,
            )
            plan_ok = bool(r.get("ok"))
            if plan_ok:
                plan_rows = _extract_plan_rows(r.get("plan"))
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"pre_lock explain 失败: {exc}")
        if plan_rows:
            # DML 行锁按行数粗估（上限 30s）
            lock_ms = min((plan_rows // 1000 + 1) * 50, 30000)
    elif kind == "ddl":
        rows = max(
            (
                int(r.get("est_rows") or 0)
                for r in (state.get("metadata") or {}).get("stats") or []
            ),
            default=0,
        )
        if rows:
            lock_ms = min((rows // 1000 + 1) * 100, 60000)
    return {
        "pre_lock": {
            "stmt": (info.get("kinds") or [None])[0],
            "lock_estimate_ms": lock_ms,
            "plan_ok": plan_ok,
            "plan_rows": plan_rows,
        }
    }


async def pre_rows_node(state: DbReviewState) -> dict:
    """影响/扫描行数估算（元数据统计）。"""
    meta = state.get("metadata") or {}
    rows = meta.get("stats") or []
    est = max((int(r.get("est_rows") or 0) for r in rows), default=0)
    return {"pre_rows": {"estimated_rows": est}}


async def pre_slow_node(state: DbReviewState) -> dict:
    """慢SQL 纯分析（不连库）。"""
    meta = state.get("metadata") or {}
    try:
        reg = getattr(app_state, "plugin_registry", None)
        slow = (
            await reg.call(
                "slow_sql_explain", sql=state.get("sql_text") or "", plan="", metadata=meta
            )
            if reg is not None
            else {}
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"pre_slow 失败: {exc}")
        slow = {"is_slow": False, "issues": [], "suggestions": []}
    return {"pre_slow": slow}


async def pre_meta_node(state: DbReviewState) -> dict:
    """元数据/规则维度（基于 sqlglot AST，方言无关）：无 WHERE / WHERE 恒真 / DROP / DDL。"""
    info = analyze_sql(state.get("sql_text") or "", state.get("db_type") or "")
    kinds = info.get("kinds") or []
    kind = info.get("kind")
    dims = {
        "is_ddl": kind == "ddl",
        "has_drop": any(k in ("Drop", "TruncateTable") for k in kinds),
        "no_where_dml": kind == "dml" and not info.get("has_where"),
        "where_always_true": bool(info.get("where_always_true")),
        "cross_db": False,
        "core_path": False,
    }
    return {"pre_meta": dims}


async def aggregate_node(state: DbReviewState) -> dict:
    """fan-in：合并各预检分支为 dimensions + slow_sql。"""
    dims = dict(state.get("pre_meta") or {})
    rows = (state.get("pre_rows") or {}).get("estimated_rows")
    if rows is not None:
        dims["estimated_rows"] = rows
    lock = (state.get("pre_lock") or {}).get("lock_estimate_ms")
    if lock is not None:
        dims["lock_estimate_ms"] = lock
    return {"dimensions": dims, "slow_sql": state.get("pre_slow") or {}}


async def grade_node(state: DbReviewState) -> dict:
    """LLM 风险分级（失败降级规则）。"""
    dimensions = state.get("dimensions") or {}
    risk = "medium"
    if (
        dimensions.get("has_drop")
        or dimensions.get("no_where_dml")
        or dimensions.get("where_always_true")
    ):
        risk = "critical"
    try:
        llm = await get_llm(AGENT_TYPE)
        prompt = GRADE_PROMPT.format(
            db_type=state.get("db_type") or "",
            target_database=state.get("target_database") or "",
            sql=(state.get("sql_text") or "")[:4000],
            metadata=json.dumps(state.get("metadata") or {}, ensure_ascii=False)[:3000],
            slow_sql=json.dumps(state.get("slow_sql") or {}, ensure_ascii=False)[:1500],
        )
        raw = await llm.ainvoke(prompt)
        content = getattr(raw, "content", str(raw))
        parsed = _parse_json(content)
        if parsed.get("risk_level"):
            risk = parsed["risk_level"]
            dimensions.update(
                {k: parsed[k] for k in ("online_ddl", "estimated_rows", "lock_estimate_ms",
                                         "core_path", "cross_db", "rollback_ready") if k in parsed}
            )
    except Exception as exc:  # noqa: BLE001 - LLM 不可用降级规则
        logger.warning(f"grade LLM 降级: {exc}")
    return {"risk_level": risk, "dimensions": dimensions}


async def suggest_node(state: DbReviewState) -> dict:
    """优化建议（LLM + 慢SQL建议合并）。"""
    suggestions: list[str] = list((state.get("slow_sql") or {}).get("suggestions") or [])
    try:
        llm = await get_llm(AGENT_TYPE)
        prompt = SUGGEST_PROMPT.format(
            sql=(state.get("sql_text") or "")[:4000],
            metadata=json.dumps(state.get("metadata") or {}, ensure_ascii=False)[:3000],
            slow_sql=json.dumps(state.get("slow_sql") or {}, ensure_ascii=False)[:1500],
        )
        raw = await llm.ainvoke(prompt)
        parsed = _parse_json(getattr(raw, "content", str(raw)))
        suggestions.extend(parsed.get("suggestions") or [])
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"suggest LLM 降级: {exc}")
    return {"suggestions": suggestions}


async def persist_node(state: DbReviewState) -> dict:
    """落库评审结果并更新变更单状态。"""
    request_id = int(state.get("request_id") or 0)
    if state.get("tool_blocked"):
        answer = state.get("answer") or "工具未在该租户启用"
        if request_id:
            async with session_scope() as session:
                await session.execute(
                    text(
                        "UPDATE agent_change_request SET status='blocked' WHERE id=:id"
                    ),
                    {"id": request_id},
                )
                await session.commit()
        return {"answer": answer}
    dimensions = state.get("dimensions") or {}
    risk = state.get("risk_level") or "medium"
    status = "approved" if risk == "low" else "pending_approval"
    answer = (
        f"风险等级：{risk}；建议：{'；'.join((state.get('suggestions') or [])[:5]) or '无'}"
    )
    if request_id:
        async with session_scope() as session:
            await session.execute(
                text(
                    "UPDATE agent_change_request SET risk_level=:risk, status=:status "
                    "WHERE id=:id"
                ),
                {"risk": risk, "status": status, "id": request_id},
            )
            await session.execute(
                text(
                    "INSERT INTO agent_change_review "
                    "(tenant_id, request_id, risk_level, online_ddl, estimated_rows, "
                    " lock_estimate_ms, core_path, cross_db, rollback_ready, slow_sql, "
                    " suggestions, metadata_snapshot, detail) "
                    "VALUES (:tenant_id,:request_id,:risk,:online_ddl,:estimated_rows,"
                    " :lock_estimate_ms,:core_path,:cross_db,:rollback_ready,"
                    " CAST(:slow_sql AS JSONB), CAST(:suggestions AS JSONB), "
                    " CAST(:metadata AS JSONB), CAST(:detail AS JSONB))"
                ),
                {
                    "tenant_id": int(state.get("tenant_id") or 0),
                    "request_id": request_id,
                    "risk": risk,
                    "online_ddl": dimensions.get("online_ddl"),
                    "estimated_rows": dimensions.get("estimated_rows"),
                    "lock_estimate_ms": dimensions.get("lock_estimate_ms"),
                    "core_path": dimensions.get("core_path"),
                    "cross_db": dimensions.get("cross_db"),
                    "rollback_ready": dimensions.get("rollback_ready"),
                    "slow_sql": json.dumps(state.get("slow_sql") or {}, ensure_ascii=False),
                    "suggestions": json.dumps(state.get("suggestions") or [], ensure_ascii=False),
                    "metadata": json.dumps(state.get("metadata") or {}, ensure_ascii=False),
                    "detail": json.dumps(state.get("dimensions") or {}, ensure_ascii=False),
                },
            )
            await session.commit()
    return {"answer": answer}


async def save_memory_node(state: DbReviewState) -> dict:
    """审批通过后抽取评审偏好，写入长期记忆（失败降级）。"""
    sql_text = str(state.get("sql_text") or "")[:200]
    risk = state.get("risk_level") or "-"
    suggestions = state.get("suggestions") or []
    approval = state.get("approval")
    approved = approval.get("approved") if isinstance(approval, dict) else None
    summary = (
        f"变更评审：SQL={sql_text}；风险={risk}；"
        f"建议={('、'.join(map(str, suggestions[:3])) or '无')}；"
        f"人工结论={'通过' if approved else '拒绝' if approved is False else '未知'}"
    )
    from backend.services.memory_hooks import persist_long_term

    await persist_long_term(agent_id="db_review", state=state, summary=summary)
    return {}


def route_load(state: DbReviewState) -> str:
    """load 后路由：工具未启用 → 直接结束（persist 保存提示）。"""
    return "blocked" if state.get("tool_blocked") else "ok"


def route_risk(state: DbReviewState) -> str:
    """分级后路由：低风险直接落库，其余进入人工审批。"""
    risk = (state.get("risk_level") or "").lower()
    return "low" if risk == "low" else "approve"
