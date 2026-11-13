"""超管菜单管理端点（/api/v1/admin/menus）。"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from backend.common.response import success
from backend.data.dao.auth.menu_dao import MenuDao
from backend.middleware.auth import CurrentUser, get_current_user
from backend.observability.exception import BizException, ErrCode
from backend.security.rbac import Scope
from backend.security.security import require_scope

router = APIRouter(tags=["admin"])


class MenuIn(BaseModel):
    """菜单项（新建 / 更新共用）。"""

    name: str = Field(..., max_length=64)
    path: str = Field(..., max_length=128)
    icon: str = Field("", max_length=64)
    parent_id: int = 0
    sort_order: int = 0
    visible: bool = True
    scope: Optional[str] = Field(None, max_length=64)


class MenuStatusIn(BaseModel):
    """状态变更（显隐）。"""

    visible: bool


@router.get("/menus", summary="菜单列表（分页，含隐藏）")
async def list_menus(
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(50, ge=1, le=200, description="每页条数"),
    menu_id: Optional[int] = Query(None, description="菜单ID（精确）"),
    parent_id: Optional[int] = Query(None, description="父级ID（精确）"),
    name: Optional[str] = Query(None, description="名称（模糊）"),
    visible: Optional[bool] = Query(None, description="启动状态（精确）：true=显示 / false=隐藏"),
    _: object = Depends(require_scope(Scope.MENU_PAGE)),  # noqa: B008
    __: object = Depends(get_current_user),  # noqa: B008
) -> Any:
    """菜单列表分页查询（含隐藏项，支持 id/父级ID 精确、名称模糊、启动状态精确过滤）。

    请求：query { page, page_size, menu_id?, parent_id?, name?, visible? }
    权限：menu:page
    返回：items / total / page / page_size
    """
    rows, total = await MenuDao.list_paged(
        page=page,
        page_size=page_size,
        menu_id=menu_id,
        parent_id=parent_id,
        name=name,
        visible=visible,
    )
    return success({"items": rows, "total": total, "page": page, "page_size": page_size})


@router.post("/menus", summary="新建菜单")
async def create_menu(
    body: MenuIn,
    _: object = Depends(require_scope(Scope.MENU_ADD)),  # noqa: B008
    current: CurrentUser = Depends(get_current_user),  # noqa: B008
) -> Any:
    """新建菜单项。

    请求：body { name, path, icon?, parent_id?, sort_order?, visible?, scope? }
    权限：menu:add
    返回：{ id }
    """
    new_id = await MenuDao.create(**body.model_dump())
    return success({"id": new_id})


@router.put("/menus/{menu_id}", summary="更新菜单")
async def update_menu(
    menu_id: int,
    body: MenuIn,
    _: object = Depends(require_scope(Scope.MENU_UPDATE)),  # noqa: B008
    current: CurrentUser = Depends(get_current_user),  # noqa: B008
) -> Any:
    """更新菜单项（禁止把自己设为父菜单）。

    请求：path { menu_id }, body { name, path, icon?, parent_id?, sort_order?, visible?, scope? }
    权限：menu:update
    返回：{ id }
    """
    if body.parent_id == menu_id:
        raise BizException(ErrCode.PARAM_ERROR, "不能把自己设为父菜单")
    await MenuDao.update(menu_id, **body.model_dump())
    return success({"id": menu_id})


@router.delete("/menus/{menu_id}", summary="删除菜单")
async def delete_menu(
    menu_id: int,
    _: object = Depends(require_scope(Scope.MENU_DELETE)),  # noqa: B008
    current: CurrentUser = Depends(get_current_user),  # noqa: B008
) -> Any:
    """删除菜单项。

    请求：path { menu_id }
    权限：menu:delete
    返回：{ id }
    """
    await MenuDao.delete(menu_id)
    return success({"id": menu_id})


@router.patch("/menus/{menu_id}/status", summary="状态变更（显隐）")
async def set_status(
    menu_id: int,
    body: MenuStatusIn,
    _: object = Depends(require_scope(Scope.MENU_STATUS)),  # noqa: B008
    current: CurrentUser = Depends(get_current_user),  # noqa: B008
):
    """切换菜单显隐状态。

    请求：path { menu_id }, body { visible: bool }
    权限：menu:status
    返回：{ id, visible }
    """
    await MenuDao.set_visible(menu_id, body.visible)
    return success({"id": menu_id, "visible": body.visible})
