"""异常体系：BizException/AuthError + AgentError 体系，统一由全局处理器包装为 {code,msg,data}。"""

from __future__ import annotations

from typing import Optional


class ErrCode:
    """业务错误码（非 0 表示失败）。"""

    OK = 0
    PARAM_ERROR = 40000
    MISSING_TENANT = 40001
    UNAUTHORIZED = 40100  # 未认证/签名缺失过期
    FORBIDDEN = 40003  # 无权限
    GUARDRAIL = 40300  # 护栏拦截（违禁词/Prompt 注入）
    NOT_FOUND = 40400
    RATE_LIMIT = 42900
    INTERNAL = 50000
    DEP_UNAVAILABLE = 50200  # 依赖（RAG/模型/检索）不可用
    HITL_PENDING = 50300  # 人工审核/排队中，稍后重试


class BizException(Exception):
    """业务异常：携带业务错误码，由全局异常处理器包装为 {code,msg,data}。"""

    def __init__(self, code: int, msg: str, http_status: int = 200) -> None:
        super().__init__(msg)
        self.code = code
        self.msg = msg
        self.http_status = http_status


class AuthError(BizException):
    """登录/鉴权业务异常（业务域专用）：凭证错误、未认证、无权限等。

    子类化 BizException，交由全局 biz_exc_handler 按 code 包装响应；
    默认 401 未认证，权限类错误传 code=ErrCode.FORBIDDEN、http_status=403。
    与裸 BizException 的区别只在「类型」——便于按 except AuthError 精准捕获，
    也明确这是鉴权域而非通用业务校验。
    """

    def __init__(self, msg: str, code: int = ErrCode.UNAUTHORIZED, http_status: int = 401) -> None:
        super().__init__(code, msg, http_status)


class AgentError(Exception):
    """Agent 平台基础异常（领域/基础设施层）。

    携带业务错误码 code（默认 INTERNAL），由 agent_err_handler 按 code 包装为 {code,msg,data}。

    与 BizException 的边界：BizException 用于「接口/业务层」预期的、由调用方主动抛出的
    业务校验错误（参数错误、找不到、无权限等业务语义），code/http_status 由调用方控制；
    AgentError 用于「领域/基础设施层」预期外的失败（配置缺失、模型/能力调用失败、跨租户访问、
    护栏拦截），code 由异常类型决定、统一兜底。两者不重复：业务校验走 BizException/AuthError，
    领域失败走 AgentError——权限/租户/护栏这类语义在两层都映射到同一套 ErrCode，避免错位。
    """

    code: int = ErrCode.INTERNAL

    def __init__(self, message: str = "", *, code: int | None = None) -> None:
        super().__init__(message)
        self.msg = message
        if code is not None:
            self.code = code


class ConfigError(AgentError):
    """配置缺失/校验失败。"""


class ModelError(AgentError):
    """模型调用失败（LLM/Embedding/Reranker/分类器）。"""


class CapabilityError(AgentError):
    """能力/插件调用失败。"""

    def __init__(
        self, message: str, *, degradable: bool = False, cause: Optional[Exception] = None
    ) -> None:
        super().__init__(message)
        # degradable=True 表示子能力失败可被主流程降级跳过（如 web_search 失败不阻断 RAG 生成）
        self.degradable = degradable
        self.__cause__ = cause


class TenantError(AgentError):
    """租户隔离/权限相关错误（跨租户访问、能力未开通等）。"""

    code = ErrCode.FORBIDDEN


class GuardrailError(AgentError):
    """输入/输出护栏拦截（违禁词、Prompt 注入等）。"""

    code = ErrCode.GUARDRAIL
