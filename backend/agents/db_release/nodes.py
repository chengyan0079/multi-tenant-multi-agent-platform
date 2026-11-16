"""db_release 节点：取 approved 变更单 → guard 校验 → 沙箱执行 → 校验结果 → 人工门禁 → 落库/输出 SQL。"""

from __future__ import annotations

from sqlalchemy import text

from backend.agents.db_release.state import DbReleaseState
from backend.app_state import app_state
from backend.common.logger import get_logger
from backend.data.dao.agent.db_connection_dao import DbConnectionDao
from backend.data.sql import fetch_one, session_scope
from backend.data.sql.audit import audit_on_insert
from backend.services.sql_script_service import analyze_sql

logger = get_logger("db_release_nodes")


async def load_request_node(state: DbReleaseState) -> dict:
    """按 request_id 取已审批变更单（SQL 来源，不接受入参 SQL）。"""
    tenant = int(state.get("tenant_id") or 0)
    rid = int(state.get("request_id") or 0)
    if not rid:
        return {"release_code": "blocked", "answer": "缺少 request_id"}
    async with session_scope() as session:
        req = await fetch_one(
            session,
            text(
                "SELECT sql_text, db_type, status FROM agent_change_request "
                "WHERE tenant_id = :t AND id = :id"
            ),
            {"t": tenant, "id": rid},
        )
    if req is None:
        return {"release_code": "blocked", "answer": "变更单不存在"}
    if (req.get("status") or "") != "approved":
        return {"release_code": "blocked", "answer": "变更单未审批通过（需 approved）"}
    # 工具校验：sql_exec_sandbox 必须在该租户启用
    reg = getattr(app_state, "plugin_registry", None)
    if reg is not None and not reg.is_tool_enabled_for_tenant(tenant, "sql_exec_sandbox"):
        return {
            "release_code": "blocked",
            "answer": "工具 sql_exec_sandbox 未在该租户启用，请先在「工具管理」绑定并启用",
        }
    return {
        "sql_text": req.get("sql_text") or "",
        "db_type": req.get("db_type") or "",
        "final_sql": req.get("sql_text") or "",
        "release_code": "ok",
    }


async def guard_node(state: DbReleaseState) -> dict:
    """执行前校验：影子库 + env=sandbox + 单语句/非事务。"""
    if state.get("release_code") != "ok":
        return {}
    conn = await DbConnectionDao.get(
        int(state.get("tenant_id") or 0), str(state.get("sandbox_connection_id") or "")
    )
    if conn is None:
        return {"release_code": "blocked", "answer": "影子库连接不存在"}
    if (conn.get("env") or "prod") != "sandbox":
        return {"release_code": "blocked", "answer": "仅允许 env=sandbox 的影子库连接"}
    info = analyze_sql(state.get("sql_text") or "", state.get("db_type") or "")
    if not info.get("ok"):
        return {"release_code": "blocked", "answer": "SQL 不合法: " + "；".join(info.get("errors") or [])}
    if len(info.get("kinds") or []) > 1:
        return {"release_code": "blocked", "answer": "仅支持单条语句"}
    if info.get("kind") == "txn":
        return {"release_code": "blocked", "answer": "不支持事务控制"}
    return {"release_code": "ok"}


async def shadow_execute_node(state: DbReleaseState) -> dict:
    """调 sql_exec_sandbox 在影子库执行（即用即弃，工具内部回滚）。"""
    if state.get("release_code") != "ok":
        return {}
    try:
        reg = getattr(app_state, "plugin_registry", None)
        if reg is None:
            return {"exec_result": {"ok": False, "error": "工具注册表未就绪"}}
        result = await reg.call(
            "sql_exec_sandbox",
            tenant_id=int(state.get("tenant_id") or 0),
            request_id=int(state.get("request_id") or 0),
            connection_id=str(state.get("sandbox_connection_id") or ""),
            execute=True,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"沙箱执行异常: {exc}")
        result = {"ok": False, "error": str(exc)}
    return {"exec_result": result}


async def verify_node(state: DbReleaseState) -> dict:
    """执行结果判定。"""
    result = state.get("exec_result") or {}
    ok = bool(result.get("exec_ok"))
    return {
        "exec_ok": ok,
        "answer": result.get("error") or ("沙箱执行成功" if ok else "沙箱执行失败"),
    }


async def save_memory_node(state: DbReleaseState) -> dict:
    """放行/拒绝后抽取发布偏好，写入长期记忆（失败降级）。"""
    exec_result = state.get("exec_result") or {}
    approval = state.get("approval")
    approved = approval.get("approved") if isinstance(approval, dict) else None
    summary = (
        f"变更发布：request={state.get('request_id')}；"
        f"沙箱={state.get('sandbox_connection_id')}；"
        f"执行={'成功' if exec_result.get('exec_ok') else '失败'}；"
        f"放行={'是' if approved else '否'}"
    )
    from backend.services.memory_hooks import persist_long_term

    await persist_long_term(agent_id="db_release", state=state, summary=summary)
    return {}


def route_load(state: DbReleaseState) -> str:
    return "ok" if state.get("release_code") == "ok" else "blocked"


def route_guard(state: DbReleaseState) -> str:
    return "ok" if state.get("release_code") == "ok" else "blocked"


async def persist_node(state: DbReleaseState) -> dict:
    """写 agent_change_release 并给出最终状态/输出 SQL。"""
    tenant = int(state.get("tenant_id") or 0)
    release_code = state.get("release_code")
    approval = state.get("approval") or {}
    result = state.get("exec_result") or {}

    if release_code == "blocked":
        status = "blocked"
        final_sql = None
    elif not state.get("exec_ok"):
        status = "failed"
        final_sql = state.get("final_sql")
    elif approval.get("approved") is True:
        status = "ready_for_prod"
        final_sql = state.get("final_sql")
    elif approval.get("approved") is False:
        status = "rejected"
        final_sql = None
    else:
        status = "pending_gate"
        final_sql = None

    async with session_scope() as session:
        await session.execute(
            text(
                "INSERT INTO agent_change_release "
                "(tenant_id, request_id, sandbox_connection_id, thread_id, exec_ok, exec_ms, affected_rows, "
                " error, sandbox_rolled_back, final_sql, status, trace_id, "
                " create_user_id, update_user_id, create_tenant_id, update_tenant_id) "
                "VALUES (:tenant_id,:request_id,:sandbox_connection_id,:thread_id,:exec_ok,:exec_ms,:affected_rows,"
                " :error,:sandbox_rolled_back,:final_sql,:status,:trace_id,"
                " :create_user_id,:update_user_id,:create_tenant_id,:update_tenant_id)"
            ),
            {
                "tenant_id": tenant,
                "request_id": int(state.get("request_id") or 0),
                "sandbox_connection_id": str(state.get("sandbox_connection_id") or ""),
                "thread_id": state.get("session_id") or state.get("thread_id"),
                "exec_ok": result.get("exec_ok"),
                "exec_ms": result.get("exec_ms"),
                "affected_rows": result.get("affected_rows"),
                "error": result.get("error"),
                "sandbox_rolled_back": result.get("rolled_back"),
                "final_sql": final_sql,
                "status": status,
                "trace_id": state.get("trace_id"),
                **audit_on_insert(tenant_id=tenant),
            },
        )
        await session.commit()

    if status == "ready_for_prod":
        answer = f"沙箱执行成功，原样 SQL 已就绪（供人工上生产）：{final_sql}"
    elif status == "rejected":
        answer = "人工拒绝，未输出 SQL（沙箱已回滚）"
    elif status == "failed":
        answer = f"沙箱执行失败：{result.get('error')}"
    elif status == "blocked":
        answer = state.get("answer") or "执行前校验未通过"
    else:
        answer = "待人工确认"
    return {"release_status": status, "final_sql": final_sql, "answer": answer}
