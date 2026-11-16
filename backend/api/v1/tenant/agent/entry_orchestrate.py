"""入口编排接口：意图识别 + 流程选择（A/B/C/D）。"""

from __future__ import annotations

import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from backend.common.response import success
from backend.middleware.auth import CurrentUser, get_current_user
from backend.security.rbac import Scope
from backend.security.security import require_scope
from backend.services.entry_orchestrator import route_and_run

router = APIRouter(prefix="/entry-orchestrate", tags=["tenant"])


class OrchestrateIn(BaseModel):
    text: str = Field(..., min_length=1, description="用户意图文本")
    thread_id: Optional[str] = None
    inputs: dict[str, Any] = Field(default_factory=dict, description="结构化输入（sql_text 等）")


class PlanIn(BaseModel):
    plan: dict[str, Any] = Field(..., description="编排计划 DSL（agent/parallel/sequence/branch/loop）")
    thread_id: Optional[str] = None
    inputs: dict[str, Any] = Field(default_factory=dict)


@router.post("/plan", summary="按编排计划 DSL 执行")
async def run_plan(
    body: PlanIn,
    request: Request,
    current: CurrentUser = Depends(get_current_user),
    _: object = Depends(require_scope(Scope.UNIFIED_ASK)),
):
    app = request.app.state.app_state
    orch = getattr(app, "orchestrator", None)
    if orch is None:
        return success({"ok": False, "error": "编排器未就绪"})
    thread_id = body.thread_id or f"t{current.tenant_id}:u{current.user_id}:{uuid.uuid4().hex}"
    inputs = {
        **body.inputs,
        "tenant_id": current.tenant_id,
        "user_id": current.user_id,
        "session_id": thread_id,
    }
    result = await orch.run_plan(body.plan, thread_id, inputs)
    return success({"thread_id": thread_id, "result": result})


@router.post("", summary="意图识别 + 流程编排执行")
async def orchestrate(
    body: OrchestrateIn,
    current: CurrentUser = Depends(get_current_user),
    _: object = Depends(require_scope(Scope.UNIFIED_ASK)),
):
    thread_id = body.thread_id or f"t{current.tenant_id}:u{current.user_id}:{uuid.uuid4().hex}"
    res = await route_and_run(
        text=body.text,
        tenant_id=current.tenant_id,
        user_id=current.user_id,
        thread_id=thread_id,
        inputs=body.inputs,
    )
    return success({"thread_id": thread_id, **res})
