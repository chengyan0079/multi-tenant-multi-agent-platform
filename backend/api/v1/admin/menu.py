"""超管菜单管理端点（/api/v1/admin/menus）。

菜单管理归权限中心，复用 rbac:read / rbac:write 两个权限点；整组已在装配处挂
require_super_admin()，模块内不再重复鉴权，仅写操作叠加 require_scope 做接口级校验。
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from backend.common.response import success
from backend.data.dao.auth.menu_dao import MenuDao
from backend.middleware.auth import CurrentUser, get_current_user
from backend.observability.exception import BizException, ErrCode
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


@router.get("/menus", summary="菜单树（全部，含隐藏）")
async def list_menus(
    _: object = Depends(require_scope("rbac:read")),  # noqa: B008
    __: object = Depends(get_current_user),  # noqa: B008
) -> Any:
    rows = await MenuDao.list_all()
    return success({"items": MenuDao.build_tree(rows), "total": len(rows)})


@router.post("/menus", summary="新建菜单")
async def create_menu(
    body: MenuIn,
    _: object = Depends(require_scope("rbac:write")),  # noqa: B008
    current: CurrentUser = Depends(get_current_user),  # noqa: B008
) -> Any:
    new_id = await MenuDao.create(**body.model_dump())
    return success({"id": new_id})


@router.put("/menus/{menu_id}", summary="更新菜单")
async def update_menu(
    menu_id: int,
    body: MenuIn,
    _: object = Depends(require_scope("rbac:write")),  # noqa: B008
    current: CurrentUser = Depends(get_current_user),  # noqa: B008
) -> Any:
    if body.parent_id == menu_id:
        raise BizException(ErrCode.PARAM_ERROR, "不能把自己设为父菜单")
    await MenuDao.update(menu_id, **body.model_dump())
    return success({"id": menu_id})


@router.delete("/menus/{menu_id}", summary="删除菜单")
async def delete_menu(
    menu_id: int,
    _: object = Depends(require_scope("rbac:write")),  # noqa: B008
    current: CurrentUser = Depends(get_current_user),  # noqa: B008
) -> Any:
    await MenuDao.delete(menu_id)
    return success({"id": menu_id})
