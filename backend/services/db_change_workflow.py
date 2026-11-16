"""数据库变更业务编排：聚合 request/review/release，推导阶段与下一步动作。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

from backend.data.sql import fetch_one, session_scope

# 阶段
SUBMITTED = "submitted"
REVIEWING = "reviewing"
PENDING_APPROVAL = "pending_approval"
APPROVED = "approved"
PENDING_GATE = "pending_gate"
READY_FOR_PROD = "ready_for_prod"
REJECTED = "rejected"
BLOCKED = "blocked"
FAILED = "failed"

# 阶段 → 可执行动作
_ACTIONS: dict[str, list[str]] = {
    SUBMITTED: ["start_review"],
    PENDING_APPROVAL: ["approve", "reject"],
    APPROVED: ["release"],
    PENDING_GATE: ["gate_approve", "gate_reject"],
    READY_FOR_PROD: ["done"],
}

_HINTS: dict[str, str] = {
    SUBMITTED: "待发起评审",
    REVIEWING: "评审进行中",
    PENDING_APPROVAL: "待人工审批（change_approve）",
    APPROVED: "评审通过，可在影子库沙箱验证",
    PENDING_GATE: "沙箱验证完成，待人工放行输出 SQL",
    READY_FOR_PROD: "已输出原样 SQL，可交人工上生产",
    REJECTED: "评审/放行被拒绝",
    BLOCKED: "执行前校验未通过",
    FAILED: "执行失败",
}


def _derive_stage(request: dict | None, release: dict | None) -> str:
    if request is None:
        return "not_found"
    status = (request.get("status") or "").lower()
    if status in ("draft",):
        return SUBMITTED
    if status in ("reviewing",):
        return REVIEWING
    if status in ("pending_approval",):
        return PENDING_APPROVAL
    if status in ("approved",):
        # 有 release 记录则以 release 状态为准
        if release:
            rs = (release.get("status") or "").lower()
            if rs in ("pending_gate",):
                return PENDING_GATE
            if rs in ("ready_for_prod",):
                return READY_FOR_PROD
            if rs in ("rejected",):
                return REJECTED
            if rs in ("blocked",):
                return BLOCKED
            if rs in ("failed",):
                return FAILED
        return APPROVED
    if status in ("rejected", "blocked", "failed"):
        return status
    return status or SUBMITTED


async def get_workflow(tenant_id: int, request_id: int) -> dict[str, Any]:
    """编排视图：request + review + release + stage + next_actions。"""
    async with session_scope() as session:
        request = await fetch_one(
            session,
            text("SELECT * FROM agent_change_request WHERE tenant_id=:t AND id=:id"),
            {"t": tenant_id, "id": request_id},
        )
        review = await fetch_one(
            session,
            text(
                "SELECT * FROM agent_change_review WHERE tenant_id=:t AND request_id=:id "
                "ORDER BY id DESC LIMIT 1"
            ),
            {"t": tenant_id, "id": request_id},
        )
        release = await fetch_one(
            session,
            text(
                "SELECT * FROM agent_change_release WHERE tenant_id=:t AND request_id=:id "
                "ORDER BY id DESC LIMIT 1"
            ),
            {"t": tenant_id, "id": request_id},
        )
    stage = _derive_stage(request, release)
    return {
        "request": request,
        "review": review,
        "release": release,
        "stage": stage,
        "stage_hint": _HINTS.get(stage, ""),
        "next_actions": _ACTIONS.get(stage, []),
    }
