"""已注册能力清单（超管）：挂在 /api/v1/admin/plugins 下。"""
from __future__ import annotations

from fastapi import APIRouter

from backend.app_state import app_state

router = APIRouter(prefix="/plugins", tags=["admin"])


@router.get("")
async def list_plugins() -> dict:
    """已注册能力/插件清单。"""
    reg = app_state.plugin_registry
    if reg is None:
        return {"capabilities": []}
    return {"capabilities": reg.list_capabilities()}
