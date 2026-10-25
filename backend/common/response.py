"""统一 API 响应信封（对齐 RAG-Ultra）

所有接口统一返回 {"code": 0, "msg": "", "data": obj}。code == 0 成功，非 0 由全局
异常处理器统一包装：业务错误码见 backend.observability.exception.ErrCode，
业务异常见该模块的 BizException / AuthError；领域异常见 AgentError 体系。
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
