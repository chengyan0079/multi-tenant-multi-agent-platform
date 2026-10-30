"""已注册能力清单（超管）：挂在 /api/v1/admin/plugins 下。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from backend.app_state import app_state
from backend.common.response import success

router = APIRouter(prefix="/plugins", tags=["admin"])


@router.get("", summary="已注册能力清单（分页）")
async def list_plugins(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
) -> Any:
    """已注册能力/插件清单。"""
    reg = app_state.plugin_registry
    # 统一走 {code,msg,data} 信封：前端请求层只认信封，裸返回会被判成业务失败
    if reg is None:
        return success({"items": [], "total": 0, "page": page, "page_size": page_size})
    caps = reg.list_capabilities()
    total = len(caps)
    start = (page - 1) * page_size
    paged = caps[start : start + page_size]
    return success({"items": paged, "total": total, "page": page, "page_size": page_size})
