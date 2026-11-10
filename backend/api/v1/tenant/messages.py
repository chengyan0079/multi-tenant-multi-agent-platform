"""租户管理员消息端点：本租户 outbox/死信列表与状态变更（tenant_id 强制取当前租户）。"""

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

router = APIRouter(prefix="/messages", tags=["tenant"])

VALID_STATUS = {"pending", "done", "failed"}


class StatusIn(BaseModel):
    status: str
    error: Optional[str] = None


@router.get("/queue", summary="本租户消息队列（outbox）列表")
async def list_queue(
    status: Optional[str] = Query(None, pattern="^(pending|sent|done|failed)$"),
    message_kind: Optional[str] = Query(
        None, pattern="^(task|broadcast)$", description="投递语义筛选"
    ),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    current: CurrentUser = Depends(get_current_user),  # noqa: B008
    _: object = Depends(require_scope(Scope.MESSAGE_PAGE)),  # noqa: B008
) -> Any:
    """本租户消息队列（outbox）分页列表。

    请求：query { status?, message_kind?, page, page_size }
    权限：message:page
    返回：items / total / page / page_size
    """
    rows, total = await OutboxDao.list_outbox(
        page, page_size, status, current.tenant_id, message_kind
    )
    return success({"items": rows, "total": total, "page": page, "page_size": page_size})


@router.get("/dead-letters", summary="本租户死信队列列表")
async def list_dead_letters(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    current: CurrentUser = Depends(get_current_user),  # noqa: B008
    _: object = Depends(require_scope(Scope.MESSAGE_PAGE)),  # noqa: B008
) -> Any:
    """本租户死信队列分页列表。

    请求：query { page, page_size }
    权限：message:page
    返回：items / total / page / page_size
    """
    rows, total = await DeadLetterDao.list_dead_letters(page, page_size, current.tenant_id)
    return success({"items": rows, "total": total, "page": page, "page_size": page_size})


@router.patch("/queue/{msg_id}", summary="更改本租户消息状态（重投/标记完成/失败）")
async def change_status(
    msg_id: str,
    body: StatusIn,
    current: CurrentUser = Depends(get_current_user),  # noqa: B008
    _: object = Depends(require_scope(Scope.MESSAGE_STATUS)),  # noqa: B008
) -> Any:
    """变更本租户消息状态（重投 pending / 标记完成 done / 标记失败 failed）。

    请求：path { msg_id }, body { status, error? }
    权限：message:status
    返回：{ id, status }
    """
    if body.status not in VALID_STATUS:
        raise BizException(ErrCode.PARAM_ERROR, f"非法状态：{body.status}")
    row = await OutboxDao.get(msg_id)
    if row is None:
        raise BizException(ErrCode.NOT_FOUND, f"消息不存在：{msg_id}")
    # 租户管理员只能改本租户消息；tenant_id 为 NULL（无租户归属）同样禁止
    if current.tenant_id is not None and row.get("tenant_id") != current.tenant_id:
        raise BizException(ErrCode.FORBIDDEN, "只能操作本租户的消息")
    await OutboxDao.update_status(msg_id, body.status, current.tenant_id, body.error)
    return success({"id": msg_id, "status": body.status})


@router.get("/queue/{msg_id}", summary="消息详情")
async def get_queue_msg(
    msg_id: str,
    current: CurrentUser = Depends(get_current_user),  # noqa: B008
    _: object = Depends(require_scope(Scope.MESSAGE_VIEW)),  # noqa: B008
) -> Any:
    """本租户消息详情（校验归属，非本租户禁看）。

    请求：path { msg_id }
    权限：message:view
    返回：单条消息明细
    """
    row = await OutboxDao.get_detail(msg_id)
    if row is None:
        raise BizException(ErrCode.NOT_FOUND, f"消息不存在: {msg_id}")
    if current.tenant_id is not None and row.get("tenant_id") != current.tenant_id:
        raise BizException(ErrCode.FORBIDDEN, "只能查看本租户的消息")
    return success(row)


@router.get("/dead-letters/{dl_id}", summary="死信详情")
async def get_dead_letter(
    dl_id: str,
    current: CurrentUser = Depends(get_current_user),  # noqa: B008
    _: object = Depends(require_scope(Scope.MESSAGE_VIEW)),  # noqa: B008
) -> Any:
    """本租户死信详情（校验归属，非本租户禁看）。

    请求：path { dl_id }
    权限：message:view
    返回：单条死信明细
    """
    row = await DeadLetterDao.get(dl_id)
    if row is None:
        raise BizException(ErrCode.NOT_FOUND, f"死信不存在: {dl_id}")
    if current.tenant_id is not None and row.get("tenant_id") != current.tenant_id:
        raise BizException(ErrCode.FORBIDDEN, "只能查看本租户的消息")
    return success(row)
