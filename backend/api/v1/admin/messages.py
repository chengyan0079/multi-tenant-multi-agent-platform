"""消息管理端点（/api/v1/admin/messages）：消息队列（outbox）/ 死信队列列表 + 状态变更。

权限：超管与租户管理员（端点级 require_scope(Scope.MESSAGE_PAGE)，装配处不挂整组超管）；
- 超管可传 tenant_id 看任意租户，不传看全量；
- 租户管理员（有租户上下文）强制只看本租户，且只能改本租户消息。
只读 + 状态变更（重投 pending / 标记完成 done / 标记失败 failed），无新增 / 删除。
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from backend.common.response import success
from backend.data.dao.ops.outbox_dao import DeadLetterDao, OutboxDao
from backend.middleware.auth import CurrentUser, get_current_user
from backend.observability.exception import BizException, ErrCode
from backend.security.rbac import Scope
from backend.security.security import require_scope

router = APIRouter(prefix="/messages", tags=["admin"])

VALID_STATUS = {"pending", "done", "failed"}


class StatusIn(BaseModel):
    status: str


def _effective_tenant(current: CurrentUser, query_tenant: Optional[int]) -> Optional[int]:
    """租户管理员（有租户上下文）只能看本租户；超管（tenant_id=None）用查询参数。"""
    return current.tenant_id if current.tenant_id is not None else query_tenant


@router.get("/queue", summary="消息队列（outbox）列表")
async def list_queue(
    status: Optional[str] = Query(None, pattern="^(pending|sent|done|failed)$"),
    tenant_id: Optional[int] = Query(None, description="仅超管可用，按租户过滤"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    _: object = Depends(require_scope(Scope.MESSAGE_PAGE)),  # noqa: B008
    current: CurrentUser = Depends(get_current_user),  # noqa: B008
) -> Any:
    eff = _effective_tenant(current, tenant_id)
    rows, total = await OutboxDao.list_outbox(page, page_size, status, eff)
    return success({"items": rows, "total": total, "page": page, "page_size": page_size})


@router.get("/dead-letters", summary="死信队列列表")
async def list_dead_letters(
    tenant_id: Optional[int] = Query(None, description="仅超管可用，按租户过滤"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    _: object = Depends(require_scope(Scope.MESSAGE_PAGE)),  # noqa: B008
    current: CurrentUser = Depends(get_current_user),  # noqa: B008
) -> Any:
    eff = _effective_tenant(current, tenant_id)
    rows, total = await DeadLetterDao.list_dead_letters(page, page_size, eff)
    return success({"items": rows, "total": total, "page": page, "page_size": page_size})


@router.patch("/queue/{msg_id}", summary="更改消息状态（重投/标记完成/失败）")
async def change_status(
    msg_id: str,
    body: StatusIn,
    _: object = Depends(require_scope(Scope.MESSAGE_STATUS)),  # noqa: B008
    current: CurrentUser = Depends(get_current_user),  # noqa: B008
) -> Any:
    if body.status not in VALID_STATUS:
        raise BizException(ErrCode.PARAM_ERROR, f"非法状态：{body.status}")
    row = await OutboxDao.get(msg_id)
    if row is None:
        raise BizException(ErrCode.NOT_FOUND, f"消息不存在：{msg_id}")
    # 租户管理员只能改本租户消息；tenant_id 为 NULL 的消息（无租户归属）同样禁止
    if current.tenant_id is not None and row.get("tenant_id") != current.tenant_id:
        raise BizException(ErrCode.FORBIDDEN, "只能操作本租户的消息")
    await OutboxDao.update_status(msg_id, body.status, current.tenant_id)
    return success({"id": msg_id, "status": body.status})


@router.get("/queue/{msg_id}", summary="消息详情")
async def get_queue_msg(
    msg_id: str,
    _: object = Depends(require_scope(Scope.MESSAGE_VIEW)),  # noqa: B008
    current: CurrentUser = Depends(get_current_user),  # noqa: B008
) -> Any:
    row = await OutboxDao.get_detail(msg_id)
    if row is None:
        raise BizException(ErrCode.NOT_FOUND, f"消息不存在: {msg_id}")
    return success(row)


@router.get("/dead-letters/{dl_id}", summary="死信详情")
async def get_dead_letter(
    dl_id: str,
    _: object = Depends(require_scope(Scope.MESSAGE_VIEW)),  # noqa: B008
    current: CurrentUser = Depends(get_current_user),  # noqa: B008
) -> Any:
    row = await DeadLetterDao.get(dl_id)
    if row is None:
        raise BizException(ErrCode.NOT_FOUND, f"死信不存在: {dl_id}")
    return success(row)
