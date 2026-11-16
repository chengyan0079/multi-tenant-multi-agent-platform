"""数据库变更评审（db_review）接口：提交 / 列表 / 详情 / 审批(恢复)。"""

from __future__ import annotations

import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import text

from backend.common.response import success
from backend.data.sql import fetch_all, fetch_one, session_scope
from backend.middleware.auth import CurrentUser, get_current_user
from backend.security.rbac import Scope
from backend.security.security import require_scope
from backend.services.sql_script_service import validate_script

router = APIRouter(prefix="/db_change", tags=["tenant"])


class SubmitIn(BaseModel):
    sql_text: str = Field(..., min_length=1)
    db_type: str = Field(..., pattern="^(mysql|postgresql)$")
    connection_id: str = Field(..., min_length=1)
    target_database: str = ""
    target_tables: list[str] = []
    script_file_id: Optional[int] = None
    drill_file_id: Optional[int] = None


class ApproveIn(BaseModel):
    approved: bool = True
    comment: str = ""


@router.post("", summary="提交变更评审")
async def submit_change(
    body: SubmitIn,
    request: Request,
    current: CurrentUser = Depends(get_current_user),
    _: object = Depends(require_scope(Scope.UNIFIED_ASK)),
):
    check = validate_script(body.sql_text, body.db_type)
    if not check.get("ok"):
        return success({"ok": False, "errors": check.get("errors"), "warnings": check.get("warnings")})

    app = request.app.state.app_state
    orch = app.orchestrator
    if orch is None:
        return success({"ok": False, "error": "编排器未就绪"})

    thread_id = f"t{current.tenant_id}:u{current.user_id}:{uuid.uuid4().hex}"
    initial: dict[str, Any] = {
        "sql_text": body.sql_text,
        "db_type": body.db_type,
        "connection_id": body.connection_id,
        "target_database": body.target_database,
        "target_tables": body.target_tables,
        "script_file_id": body.script_file_id,
        "drill_file_id": body.drill_file_id,
        "tenant_id": current.tenant_id,
        "user_id": current.user_id,
        "session_id": thread_id,
        "turn_id": uuid.uuid4().hex,
        "trace_id": uuid.uuid4().hex,
    }
    result = await orch.run_agent("db_review", thread_id, initial)
    interrupted = "__interrupt__" in result
    return success(
        {
            "ok": True,
            "thread_id": thread_id,
            "request_id": result.get("request_id"),
            "risk_level": result.get("risk_level"),
            "answer": result.get("answer"),
            "suggestions": result.get("suggestions") or [],
            "metadata": result.get("metadata") or {},
            "slow_sql": result.get("slow_sql") or {},
            "status": (
                "blocked"
                if result.get("tool_blocked")
                else ("pending_approval" if interrupted else "done")
            ),
            "gate": result.get("approval_gate"),
        }
    )


@router.get("", summary="变更单列表")
async def list_changes(
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    current: CurrentUser = Depends(get_current_user),
    _: object = Depends(require_scope(Scope.UNIFIED_ASK)),
):
    where = "WHERE tenant_id = :tenant_id"
    params: dict[str, Any] = {"tenant_id": current.tenant_id, "limit": page_size, "offset": (page - 1) * page_size}
    if status:
        where += " AND status = :status"
        params["status"] = status
    async with session_scope() as session:
        rows = await fetch_all(
            session,
            text(
                "SELECT id, title, target_database, db_type, risk_level, status, thread_id, create_at "
                f"FROM agent_change_request {where} ORDER BY id DESC "
                "LIMIT :limit OFFSET :offset"
            ),
            params,
        )
        total_row = await fetch_one(
            session,
            text(f"SELECT count(*) AS c FROM agent_change_request {where}"),
            {k: v for k, v in params.items() if k not in ("limit", "offset")},
        )
    return success(
        {"items": rows, "total": int((total_row or {}).get("c") or 0), "page": page, "page_size": page_size}
    )


@router.get("/{request_id}", summary="变更单详情（含评审）")
async def get_change(
    request_id: int,
    current: CurrentUser = Depends(get_current_user),
    _: object = Depends(require_scope(Scope.UNIFIED_ASK)),
):
    async with session_scope() as session:
        req = await fetch_one(
            session,
            text("SELECT * FROM agent_change_request WHERE tenant_id=:tid AND id=:id"),
            {"tid": current.tenant_id, "id": request_id},
        )
        review = await fetch_one(
            session,
            text(
                "SELECT * FROM agent_change_review WHERE tenant_id=:tid AND request_id=:id "
                "ORDER BY id DESC LIMIT 1"
            ),
            {"tid": current.tenant_id, "id": request_id},
        )
    return success({"request": req, "review": review})


@router.post("/{thread_id}/approve", summary="审批（HITL 恢复）")
async def approve_change(
    thread_id: str,
    body: ApproveIn,
    request: Request,
    current: CurrentUser = Depends(get_current_user),
    _: object = Depends(require_scope(Scope.UNIFIED_ASK)),
):
    app = request.app.state.app_state
    orch = app.orchestrator
    if orch is None:
        return success({"ok": False, "error": "编排器未就绪"})
    result = await orch.resume(
        "db_review", thread_id, {"approved": body.approved, "comment": body.comment}
    )
    return success(
        {
            "ok": True,
            "status": "approved" if body.approved else "rejected",
            "risk_level": result.get("risk_level"),
        }
    )


class ReleaseIn(BaseModel):
    sandbox_connection_id: str = Field(..., min_length=1, description="影子库连接ID(env=sandbox)")
    execute: bool = True


@router.post("/{request_id}/release", summary="沙箱验证已审批变更单")
async def release_change(
    request_id: int,
    body: ReleaseIn,
    request: Request,
    current: CurrentUser = Depends(get_current_user),
    _: object = Depends(require_scope(Scope.UNIFIED_ASK)),
):
    app = request.app.state.app_state
    orch = app.orchestrator
    if orch is None:
        return success({"ok": False, "error": "编排器未就绪"})
    thread_id = f"t{current.tenant_id}:u{current.user_id}:{uuid.uuid4().hex}"
    initial: dict[str, Any] = {
        "request_id": request_id,
        "sandbox_connection_id": body.sandbox_connection_id,
        "tenant_id": current.tenant_id,
        "user_id": current.user_id,
        "session_id": thread_id,
        "turn_id": uuid.uuid4().hex,
        "trace_id": uuid.uuid4().hex,
    }
    result = await orch.run_agent("db_release", thread_id, initial)
    interrupted = "__interrupt__" in result
    if interrupted:
        exec_result = result.get("exec_result") or {}
        async with session_scope() as session:
            await session.execute(
                text(
                    "INSERT INTO agent_change_release "
                    "(tenant_id, request_id, sandbox_connection_id, thread_id, exec_ok, exec_ms, affected_rows, "
                    " error, sandbox_rolled_back, final_sql, status, trace_id, "
                    " create_user_id, update_user_id, create_tenant_id, update_tenant_id) "
                    "VALUES (:tenant_id,:request_id,:scid,:thread_id,:exec_ok,:exec_ms,:affected_rows,"
                    " :error,:rolled,:final_sql,'pending_gate',:trace_id,"
                    " :create_user_id,:update_user_id,:create_tenant_id,:update_tenant_id)"
                ),
                {
                    "tenant_id": current.tenant_id,
                    "request_id": request_id,
                    "scid": body.sandbox_connection_id,
                    "thread_id": thread_id,
                    "exec_ok": exec_result.get("exec_ok"),
                    "exec_ms": exec_result.get("exec_ms"),
                    "affected_rows": exec_result.get("affected_rows"),
                    "error": exec_result.get("error"),
                    "rolled": exec_result.get("rolled_back"),
                    "final_sql": result.get("final_sql"),
                    "trace_id": initial["trace_id"],
                    "create_user_id": current.user_id,
                    "update_user_id": current.user_id,
                    "create_tenant_id": current.tenant_id,
                    "update_tenant_id": current.tenant_id,
                },
            )
            await session.commit()
    return success(
        {
            "ok": True,
            "thread_id": thread_id,
            "request_id": request_id,
            "final_sql": result.get("final_sql"),
            "exec_result": result.get("exec_result") or {},
            "release_status": result.get("release_status"),
            "answer": result.get("answer"),
            "status": "pending_gate" if interrupted else result.get("release_status"),
            "gate": result.get("approval_gate"),
        }
    )


@router.get("/{request_id}/release", summary="变更发布结果")
async def get_release(
    request_id: int,
    current: CurrentUser = Depends(get_current_user),
    _: object = Depends(require_scope(Scope.UNIFIED_ASK)),
):
    async with session_scope() as session:
        row = await fetch_one(
            session,
            text(
                "SELECT * FROM agent_change_release "
                "WHERE tenant_id = :t AND request_id = :id ORDER BY id DESC LIMIT 1"
            ),
            {"t": current.tenant_id, "id": request_id},
        )
    return success(row)


@router.get("/{request_id}/workflow", summary="变更业务编排视图")
async def get_workflow_view(
    request_id: int,
    current: CurrentUser = Depends(get_current_user),
    _: object = Depends(require_scope(Scope.UNIFIED_ASK)),
):
    from backend.services.db_change_workflow import get_workflow

    return success(await get_workflow(current.tenant_id, request_id))


class AdvanceIn(BaseModel):
    action: str = Field(..., description="approve/reject/release/gate_approve/gate_reject")
    thread_id: Optional[str] = None
    sandbox_connection_id: Optional[str] = None


@router.post("/{request_id}/advance", summary="业务编排推进")
async def advance_workflow(
    request_id: int,
    body: AdvanceIn,
    request: Request,
    current: CurrentUser = Depends(get_current_user),
    _: object = Depends(require_scope(Scope.UNIFIED_ASK)),
):
    app = request.app.state.app_state
    orch = app.orchestrator
    if orch is None:
        return success({"ok": False, "error": "编排器未就绪"})

    action = body.action
    if action in ("approve", "reject"):
        if not body.thread_id:
            return success({"ok": False, "error": "缺少 thread_id"})
        result = await orch.resume(
            "db_review", body.thread_id, {"approved": action == "approve"}
        )
        return success({"ok": True, "action": action, "risk_level": result.get("risk_level")})

    if action == "release":
        if not body.sandbox_connection_id:
            return success({"ok": False, "error": "缺少 sandbox_connection_id"})
        thread_id = f"t{current.tenant_id}:u{current.user_id}:{uuid.uuid4().hex}"
        result = await orch.run_agent(
            "db_release",
            thread_id,
            {
                "request_id": request_id,
                "sandbox_connection_id": body.sandbox_connection_id,
                "tenant_id": current.tenant_id,
                "user_id": current.user_id,
                "session_id": thread_id,
                "turn_id": uuid.uuid4().hex,
                "trace_id": uuid.uuid4().hex,
            },
        )
        return success(
            {
                "ok": True,
                "action": action,
                "thread_id": thread_id,
                "status": "pending_gate" if "__interrupt__" in result else result.get("release_status"),
                "final_sql": result.get("final_sql"),
                "exec_result": result.get("exec_result") or {},
            }
        )

    if action in ("gate_approve", "gate_reject"):
        if not body.thread_id:
            return success({"ok": False, "error": "缺少 thread_id"})
        result = await orch.resume(
            "db_release", body.thread_id, {"approved": action == "gate_approve"}
        )
        return success(
            {
                "ok": True,
                "action": action,
                "release_status": result.get("release_status"),
                "final_sql": result.get("final_sql"),
            }
        )

    if action == "start_review":
        return success({"ok": False, "error": "请使用 POST /db_change 提交评审"})

    return success({"ok": False, "error": f"不支持的动作: {action}"})


@router.post("/release/{thread_id}/approve", summary="发布审批（gate_approve 恢复）")
async def approve_release(
    thread_id: str,
    body: ApproveIn,
    request: Request,
    current: CurrentUser = Depends(get_current_user),
    _: object = Depends(require_scope(Scope.UNIFIED_ASK)),
):
    app = request.app.state.app_state
    orch = app.orchestrator
    if orch is None:
        return success({"ok": False, "error": "编排器未就绪"})
    result = await orch.resume(
        "db_release", thread_id, {"approved": body.approved, "comment": body.comment}
    )
    return success(
        {
            "ok": True,
            "release_status": result.get("release_status"),
            "final_sql": result.get("final_sql"),
        }
    )
