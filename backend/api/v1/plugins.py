"""已注册能力清单。"""
from __future__ import annotations

from fastapi import APIRouter

from backend.app_state import app_state

router = APIRouter(prefix="/v1/plugins", tags=["plugins"])


@router.get("")
async def list_plugins() -> dict:
    """已注册能力/插件清单。"""
    reg = app_state.plugin_registry
    if reg is None:
        return {"capabilities": []}
    return {"capabilities": reg.list_capabilities()}
