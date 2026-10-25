"""已注册能力清单（超管）：挂在 /api/v1/admin/plugins 下。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from backend.app_state import app_state
from backend.common.response import success

router = APIRouter(prefix="/plugins", tags=["admin"])


@router.get("")
async def list_plugins() -> Any:
    """已注册能力/插件清单。"""
    reg = app_state.plugin_registry
    # 统一走 {code,msg,data} 信封：前端请求层只认信封，裸返回会被判成业务失败
    if reg is None:
        return success({"capabilities": []})
    return success({"capabilities": reg.list_capabilities()})
