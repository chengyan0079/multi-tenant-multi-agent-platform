"""会话域接口请求模型。"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ChatIn(BaseModel):
    """统一聊天入口请求体。"""
    text: str = Field(..., min_length=1, description="用户输入文本")


class ResumeIn(BaseModel):
    """HITL resume 请求体：注入决策后继续被挂起的图。"""
    agent_type: str = ""
    value: dict[str, Any] = Field(default_factory=dict)
