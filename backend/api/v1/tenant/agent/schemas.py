"""编排运维接口请求模型。"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class OrchestratorRunIn(BaseModel):
    """运行 agent 或 pipeline 的请求体。"""
    agent_type: Optional[str] = Field(None, description="目标 agent 类型（与 pipeline_plan 二选一）")
    pipeline_plan: Optional[list[dict[str, Any]]] = Field(default_factory=list, description="pipeline 计划")
    # thread_id 必填：checkpointer 以 thread_id 作为 checkpoint 分区键，缺省 "default" 会让所有
    # 未传 thread_id 的请求共享同一会话、互相覆盖多轮状态。必须是当前用户归属的 thread。
    thread_id: str = Field(..., description="会话 ID（必填，须为当前用户归属的 thread）")
    inputs: dict[str, Any] = Field(default_factory=dict, description="运行时输入参数")


class OrchestratorResumeIn(BaseModel):
    """HITL resume 请求体。"""
    agent_type: str = Field(..., description="目标 agent 类型（必填）")
    # thread_id 必填：空串同样会让 resume 接错会话（与 run 同样的 checkpoint 串扰风险）。
    thread_id: str = Field(..., description="会话 ID（必填，须为当前用户归属的 thread）")
    value: dict[str, Any] = Field(default_factory=dict)
