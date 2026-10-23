"""
exception - 异常体系

三层兜底语义：可降级异常允许编排在子能力失败时继续，不可降级异常中断流程。
"""
from __future__ import annotations

from typing import Optional


class AgentError(Exception):
    """Agent 平台基础异常。"""


class ConfigError(AgentError):
    """配置缺失/校验失败。"""


class ModelError(AgentError):
    """模型调用失败（LLM/Embedding/Reranker/分类器）。"""


class CapabilityError(AgentError):
    """能力/插件调用失败。"""

    def __init__(self, message: str, *, degradable: bool = False, cause: Optional[Exception] = None) -> None:
        super().__init__(message)
        # degradable=True 表示子能力失败可被主流程降级跳过（如 web_search 失败不阻断 RAG 生成）
        self.degradable = degradable
        self.__cause__ = cause


class TenantError(AgentError):
    """租户隔离/权限相关错误（跨租户访问、能力未开通等）。"""


class GuardrailError(AgentError):
    """输入/输出护栏拦截（违禁词、Prompt 注入等）。"""
