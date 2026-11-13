"""工具目录读写：agent_tool 表的运行配置（JSON 文本）。"""

from __future__ import annotations

import json
from typing import Any, Dict

from sqlalchemy import text

from backend.data.sql import fetch_value, session_scope


async def get_tool_config(name: str) -> Dict[str, Any]:
    """读 agent_tool.config（JSON 文本）；未命中或解析失败返回空 dict。"""
    async with session_scope() as s:
        raw = await fetch_value(
            s, text("SELECT config FROM agent_tool WHERE name = :name"), {"name": name}
        )
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
