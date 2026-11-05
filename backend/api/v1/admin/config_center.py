"""配置中心审批流 + 直读 Nacos 端点：/api/v1/admin/config。

协同流程（不再仅超管）：
- 配置读取（list/detail/history/groups）直接走 Nacos Open API，不落本地库；
- 所有角色可 查看(page/view)、提交申请(add)、撤回自己的待复核申请(update)；
- 仅超管与租户管理员可 复核(review)、执行写 Nacos(execute)、删除(delete)。
各端点按 scope 自行判定；所有 Nacos 写仅在 execute 触发。
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query

from backend.api.v1.admin.schemas import (
    ConfigAddIn, ConfigModifyIn, ConfigDeleteIn, RollbackRequestIn,
)
from backend.common.config_center import (
    ConfigCenterError,
    get_config_center_client,
)
from backend.common.config_center import service
from backend.common.config_center.service import OP_ADD, OP_MODIFY, OP_DELETE, RV_PASS, RV_REJECT
from backend.common.response import success
from backend.middleware.auth import CurrentUser, get_current_user
from backend.observability.exception import BizException
from backend.security.rbac import Scope
from backend.security.security import require_scope

router = APIRouter(prefix="/config", tags=["admin"])


# ---------- 直读 Nacos（配置列表 / 分组 / 详情 / 历史） ----------

@router.get("/list", summary="配置列表（直接读 Nacos，按 group 过滤+分页）")
async def list_configs(
    group: Optional[str] = Query(None, description="分组，默认全部"),
    data_id: Optional[str] = Query(None, description="dataId 模糊匹配"),
    page_no: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _: object = Depends(require_scope(Scope.CONFIG_PAGE)),  # noqa: B008
    __: object = Depends(get_current_user),  # noqa: B008
):
    client = get_config_center_client()
    try:
        data = await client.list_configs(
            data_id=data_id or "", group=group,
            page_no=page_no, page_size=page_size, with_meta=True,
        )
    except ConfigCenterError as e:
        raise BizException(50200, f"Nacos 读取失败: {e}")
    return success(data or {})


@router.get("/groups", summary="所有分组（去重，默认全部）")
async def list_groups(
    _: object = Depends(require_scope(Scope.CONFIG_PAGE)),  # noqa: B008
    __: object = Depends(get_current_user),  # noqa: B008
):
    client = get_config_center_client()
    try:
        data = await client.list_configs(data_id="", group=None, page_no=1, page_size=1000)
    except ConfigCenterError as e:
        raise BizException(50200, f"Nacos 读取失败: {e}")
    items = (data or {}).get("pageItems") or []
    groups = sorted({it.get("groupName") for it in items if it.get("groupName")})
    return success({"groups": groups})


@router.get("/detail", summary="配置当前内容（读 Nacos）")
async def get_config_detail(
    data_id: str = Query(..., description="Nacos 配置ID"),
    group: Optional[str] = Query(None, description="分组，默认客户端默认组"),
    _: object = Depends(require_scope(Scope.CONFIG_VIEW)),  # noqa: B008
    __: object = Depends(get_current_user),  # noqa: B008
):
    client = get_config_center_client()
    try:
        info = await client.get_config_info(data_id, group)
    except ConfigCenterError as e:
        raise BizException(50200, f"Nacos 读取失败: {e}")
    info = info if isinstance(info, dict) else {}
    modify_time = info.get("modifyTime") or info.get("lastModified")
    return success({
        "data_id": data_id,
        "group": group,
        "content": info.get("content"),
        "type": info.get("type"),
        "md5": info.get("md5"),
        "createTime": info.get("createTime"),
        "modifyTime": modify_time,
        "lastModified": modify_time or info.get("createTime"),
    })


@router.get("/history", summary="配置历史版本（读 Nacos）")
async def list_history(
    data_id: str = Query(..., description="Nacos 配置ID"),
    group: Optional[str] = Query(None, description="分组，默认客户端默认组"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _: object = Depends(require_scope(Scope.CONFIG_VIEW)),  # noqa: B008
    __: object = Depends(get_current_user),  # noqa: B008
):
    client = get_config_center_client()
    try:
        data = await client.list_history(
            data_id, group, page_no=page, page_size=page_size
        )
    except ConfigCenterError as e:
        raise BizException(50200, f"Nacos 读取失败: {e}")
    return success(data or {})


@router.get("/history/detail", summary="配置历史版本详情（读 Nacos）")
async def get_history_detail(
    data_id: str = Query(..., description="Nacos 配置ID"),
    group: Optional[str] = Query(None, description="分组，默认客户端默认组"),
    nid: int = Query(..., description="历史版本 nid"),
    _: object = Depends(require_scope(Scope.CONFIG_VIEW)),  # noqa: B008
    __: object = Depends(get_current_user),  # noqa: B008
):
    client = get_config_center_client()
    try:
        data = await client.get_history(data_id, nid, group)
    except ConfigCenterError as e:
        raise BizException(50200, f"Nacos 读取失败: {e}")
    return success(data or {})


# ---------- 审批流（申请 / 复核 / 执行 / 回滚 / 列表） ----------

@router.post("/requests/add", summary="新增配置申请")
async def create_add(  # noqa: B008
    _: object = Depends(require_scope(Scope.CONFIG_ADD)),  # noqa: B008
    current: CurrentUser = Depends(get_current_user),  # noqa: B008
    body: ConfigAddIn = ...,
):
    async with _session() as s:
        req = await service.create_request(
            s, namespace=body.namespace, group_id=body.group_id, data_id=body.data_id,
            op_type=OP_ADD, title=body.title,
            content_new=body.content_new, content_format=body.content_format, reason=body.reason,
        )
    return success({"id": req["id"], "status": req["status"]})


@router.post("/requests/modify", summary="修改配置申请")
async def create_modify(  # noqa: B008
    _: object = Depends(require_scope(Scope.CONFIG_UPDATE)),  # noqa: B008
    current: CurrentUser = Depends(get_current_user),  # noqa: B008
    body: ConfigModifyIn = ...,
):
    async with _session() as s:
        req = await service.create_request(
            s, namespace=body.namespace, group_id=body.group_id, data_id=body.data_id,
            op_type=OP_MODIFY, title=body.title,
            content_new=body.content_new, content_format=body.content_format, reason=body.reason,
        )
    return success({"id": req["id"], "status": req["status"]})


@router.post("/requests/delete", summary="删除配置申请")
async def create_delete(  # noqa: B008
    _: object = Depends(require_scope(Scope.CONFIG_DELETE)),  # noqa: B008
    current: CurrentUser = Depends(get_current_user),  # noqa: B008
    body: ConfigDeleteIn = ...,
):
    async with _session() as s:
        req = await service.create_request(
            s, namespace=body.namespace, group_id=body.group_id, data_id=body.data_id,
            op_type=OP_DELETE, title=body.title,
            content_new=None, content_format=body.content_format, reason=body.reason,
        )
    return success({"id": req["id"], "status": req["status"]})


@router.post("/requests/rollback", summary="发起回滚申请")
async def create_rollback(  # noqa: B008
    _: object = Depends(require_scope(Scope.CONFIG_ROLLBACK)),  # noqa: B008
    current: CurrentUser = Depends(get_current_user),  # noqa: B008
    body: RollbackRequestIn = ...,
):
    async with _session() as s:
        req = await service.create_rollback(
            s, namespace=body.namespace, group_id=body.group_id, data_id=body.data_id,
            src_history_nid=body.src_history_nid,
            title=body.title, reason=body.reason, content_format=body.content_format,
        )
    return success({"id": req["id"], "status": req["status"]})


@router.get("/reviews", summary="审核日志（全量复核记录，只读列表）")
async def list_review_logs(  # noqa: B008
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _: object = Depends(require_scope(Scope.CONFIG_VIEW)),  # noqa: B008
    __: object = Depends(get_current_user),  # noqa: B008
):
    async with _session() as s:
        rows, total = await service.list_review_logs(s, page=page, page_size=page_size)
    return success({
        "items": [{
            "id": r["id"], "approval_id": r["approval_id"],
            "reviewer_user_id": r["reviewer_user_id"],
            "reviewer_name": r.get("reviewer_name"),
            "action": r["action"], "action_name": r.get("action_name"),
            "comment": r["comment"], "create_at": r["create_at"],
            "namespace": r.get("namespace"), "group_id": r.get("group_id"),
            "data_id": r.get("data_id"),
            "op_type": r.get("op_type"), "op_type_name": r.get("op_type_name"),
            "title": r.get("title"), "approval_status": r.get("approval_status"),
        } for r in rows],
        "total": total, "page": page, "page_size": page_size,
    })


@router.get("/requests", summary="审批单列表（复核人看全部，普通用户只看自己）")
async def list_requests(
    status: Optional[int] = Query(None),
    group_id: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _: object = Depends(require_scope(Scope.CONFIG_PAGE)),  # noqa: B008
    current: CurrentUser = Depends(get_current_user),  # noqa: B008
):
    # 复核人（拥有 config:execute 权限）看全部；普通用户只看自己提交的申请
    applicant_user_id = None if Scope.CONFIG_EXECUTE in current.scopes else str(current.user_id)
    async with _session() as s:
        rows, total = await service.list_requests(
            s, status=status, group_id=group_id, applicant_user_id=applicant_user_id,
            page=page, page_size=page_size)
    return success({
        "items": [{
            "id": r["id"], "namespace": r["namespace"], "group_id": r["group_id"],
            "data_id": r["data_id"], "op_type": r["op_type"],
            "title": r["title"], "status": r["status"],
            "applicant_user_id": r["applicant_user_id"],
            "applicant_name": r.get("applicant_name"),
            "reviewer_user_id": r["reviewer_user_id"],
            "reviewer_name": r.get("reviewer_name"),
            "effective_at": r.get("effective_at"),
            "create_at": r["create_at"],
        } for r in rows],
        "total": total, "page": page, "page_size": page_size,
    })


@router.get("/requests/{request_id}", summary="审批单详情")
async def get_detail(  # noqa: B008
    request_id: int,
    _: object = Depends(require_scope(Scope.CONFIG_VIEW)),  # noqa: B008
    current: CurrentUser = Depends(get_current_user),  # noqa: B008
):
    async with _session() as s:
        detail = await service.get_request_detail(s, request_id=request_id)
    return success(detail)


@router.get("/requests/{request_id}/reviews", summary="审核历史（按 approval_id 查 agent_config_review）")
async def list_reviews(  # noqa: B008
    request_id: int,
    _: object = Depends(require_scope(Scope.CONFIG_VIEW)),  # noqa: B008
    __: object = Depends(get_current_user),  # noqa: B008
):
    async with _session() as s:
        reviews = await service.get_reviews(s, approval_id=request_id)
    return success({
        "items": [{
            "id": r["id"], "approval_id": r["approval_id"],
            "reviewer_user_id": r["reviewer_user_id"],
            "reviewer_name": r.get("reviewer_name"), "action": r["action"],
            "comment": r["comment"], "create_at": r["create_at"],
        } for r in reviews],
    })


@router.post("/requests/{request_id}/approve", summary="审批通过（通过即写 Nacos，仅复核人）")
async def approve(  # noqa: B008
    request_id: int,
    comment: Optional[str] = Query(None, description="复核意见"),
    _: object = Depends(require_scope(Scope.CONFIG_EXECUTE)),  # noqa: B008
    current: CurrentUser = Depends(get_current_user),  # noqa: B008
):
    async with _session() as s:
        req = await service.review(s, request_id=request_id, action=RV_PASS, comment=comment)
    return success({"id": req["id"], "status": req["status"]})


@router.post("/requests/{request_id}/reject", summary="驳回（仅复核人）")
async def reject(  # noqa: B008
    request_id: int,
    comment: Optional[str] = Query(None, description="驳回意见（建议填写）"),
    _: object = Depends(require_scope(Scope.CONFIG_EXECUTE)),  # noqa: B008
    current: CurrentUser = Depends(get_current_user),  # noqa: B008
):
    async with _session() as s:
        req = await service.review(s, request_id=request_id, action=RV_REJECT, comment=comment)
    return success({"id": req["id"], "status": req["status"]})


@router.post("/requests/{request_id}/withdraw", summary="撤回自己的待复核申请（所有角色）")
async def withdraw(  # noqa: B008
    request_id: int,
    _: object = Depends(require_scope(Scope.CONFIG_UPDATE)),  # noqa: B008
    current: CurrentUser = Depends(get_current_user),  # noqa: B008
):
    async with _session() as s:
        req = await service.withdraw_request(s, request_id=request_id, user_id=current.user_id)
    return success({"id": req["id"], "status": req.get("status")})


def _session():
    """复用 SQL 层的 session_scope（避免顶层循环导入）。"""
    from backend.data.sql import session_scope

    return session_scope()
