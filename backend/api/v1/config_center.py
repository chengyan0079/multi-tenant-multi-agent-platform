"""配置中心审批流端点（对齐 RAG-Ultra routes_config_write / read）。

两段式：先申请→复核通过(待执行)→执行(写 Nacos)。所有 Nacos 写仅在 execute 触发。
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from backend.api.exceptions import BizException
from backend.common.response import success
from backend.core.config_center import service
from backend.middleware.auth import get_current_user

router = APIRouter(prefix="/api/v1/config", tags=["config-center"])


class CreateRequestIn(BaseModel):
    namespace: str
    group_id: str
    data_id: str
    domain: str = "prompt"
    op_type: int  # 1=新增 2=修改 3=删除
    title: Optional[str] = None
    content_new: Optional[str] = None
    content_format: str = "json"
    reason: Optional[str] = None


class RollbackRequestIn(BaseModel):
    namespace: str
    group_id: str
    data_id: str
    domain: str = "prompt"
    src_history_nid: int
    title: Optional[str] = None
    reason: Optional[str] = None


class ReviewIn(BaseModel):
    action: int  # 1=通过 2=驳回
    comment: Optional[str] = None


@router.post("/requests", summary="发起配置变更申请")
async def create_request(_: dict = Depends(get_current_user), body: CreateRequestIn = ...):  # noqa: B008
    async with _session() as s:
        req = await service.create_request(
            s, namespace=body.namespace, group_id=body.group_id, data_id=body.data_id,
            domain=body.domain, op_type=body.op_type, title=body.title,
            content_new=body.content_new, content_format=body.content_format, reason=body.reason,
        )
        await s.commit()
    return success({"id": req.id, "status": req.status})


@router.post("/requests/rollback", summary="发起回滚申请")
async def create_rollback(_: dict = Depends(get_current_user), body: RollbackRequestIn = ...):  # noqa: B008
    async with _session() as s:
        req = await service.create_rollback(
            s, namespace=body.namespace, group_id=body.group_id, data_id=body.data_id,
            domain=body.domain, src_history_nid=body.src_history_nid,
            title=body.title, reason=body.reason,
        )
        await s.commit()
    return success({"id": req.id, "status": req.status})


@router.get("/requests", summary="申请列表")
async def list_requests(
    status: Optional[int] = Query(None),
    domain: Optional[str] = Query(None),
    applicant: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    async with _session() as s:
        rows, total = await service.list_requests(
            s, status=status, domain=domain, applicant=applicant, page=page, page_size=page_size)
    return success({
        "items": [{
            "id": r.id, "namespace": r.namespace, "group_id": r.group_id, "data_id": r.data_id,
            "domain": r.domain, "op_type": r.op_type, "title": r.title, "status": r.status,
            "applicant": r.applicant, "reviewer": r.reviewer, "created_at": r.created_at,
        } for r in rows],
        "total": total, "page": page, "page_size": page_size,
    })


@router.get("/requests/{request_id}", summary="申请详情")
async def get_detail(request_id: int):
    async with _session() as s:
        detail = await service.get_request_detail(s, request_id=request_id)
    return success(detail)


@router.post("/requests/{request_id}/review", summary="复核（通过/驳回）")
async def review(request_id: int, body: ReviewIn = ...):  # noqa: B008
    async with _session() as s:
        req = await service.review(s, request_id=request_id, action=body.action, comment=body.comment)
        await s.commit()
    return success({"id": req.id, "status": req.status})


@router.post("/requests/{request_id}/execute", summary="执行（写 Nacos）")
async def execute(request_id: int):
    async with _session() as s:
        req = await service.execute_request(s, request_id=request_id)
        await s.commit()
    return success({"id": req.id, "status": req.status})


def _session():
    """复用 models.session_scope（避免顶层循环导入）。"""
    from backend.orm_models import session_scope

    return session_scope()
