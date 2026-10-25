"""编排运维接口请求模型。"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class OrchestratorRunIn(BaseModel):
    """运行 agent 或 pipeline 的请求体。"""
    agent_type: Optional[str] = Field(None, description="目标 agent 类型（与 pipeline_plan 二选一）")
    pipeline_plan: Optional[list[dict[str, Any]]] = Field(default_factory=list, description="pipeline 计划")
    thread_id: str = Field("default", description="会话 ID")
    inputs: dict[str, Any] = Field(default_factory=dict, description="运行时输入参数")


class OrchestratorResumeIn(BaseModel):
    """HITL resume 请求体。"""
    agent_type: str = ""
    thread_id: str = ""
    value: dict[str, Any] = Field(default_factory=dict)
