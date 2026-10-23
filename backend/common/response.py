"""统一 API 响应与错误码（对齐 RAG-Ultra）

所有接口统一返回 {"code": 0, "msg": "", "data": obj}：
- code == 0 成功；非 0 见 ErrCode
- 业务异常抛出 BizException；HTTP / 校验 / 未捕获异常由全局处理器统一包装
"""
from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    """统一响应信封：{"code":0,"msg":"","data": <T>}。泛型 T 描述 data 结构。"""

    code: int = 0
    msg: str = ""
    data: T | None = None


def success(data: T | None = None, msg: str = "") -> "ApiResponse[T]":
    return ApiResponse(code=0, msg=msg, data=data)


def fail(code: int, msg: str, data: Any = None) -> ApiResponse:
    return ApiResponse(code=code, msg=msg, data=data)


class BizException(Exception):
    """业务异常：携带业务错误码，由全局异常处理器包装为 {code,msg,data}。"""

    def __init__(self, code: int, msg: str, http_status: int = 200) -> None:
        super().__init__(msg)
        self.code = code
        self.msg = msg
        self.http_status = http_status


class ErrCode:
    """业务错误码（非 0 表示失败）。"""

    OK = 0
    PARAM_ERROR = 40000
    MISSING_TENANT = 40001
    UNAUTHORIZED = 40100      # 未认证/签名缺失过期
    FORBIDDEN = 40003         # 无权限
    GUARDRAIL = 40300         # 护栏拦截（违禁词/Prompt 注入）
    NOT_FOUND = 40400
    RATE_LIMIT = 42900
    INTERNAL = 50000
    DEP_UNAVAILABLE = 50200   # 依赖（RAG/模型/检索）不可用
    HITL_PENDING = 50300      # 人工审核/排队中，稍后重试
