"""统一 API 响应信封（全项目共用）

所有接口统一返回 {"code": 0, "msg": "", "data": obj}。code == 0 成功，非 0 由全局
异常处理器统一包装：业务错误码见 backend.observability.exception.ErrCode，
业务异常见该模块的 BizException / AuthError；领域异常见 AgentError 体系。
"""
from __future__ import annotations

import re
from typing import Any, Generic, TypeVar

from fastapi.responses import JSONResponse
from pydantic import BaseModel

T = TypeVar("T")

# ISO-8601 且带 T 分隔符的 datetime 字符串（可选微秒、可选时区）
_ISO_DT_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:?\d{2})?$"
)


def _normalize_datetimes(obj: Any) -> Any:
    """递归把 JSON 响应里的 ISO-8601 datetime 字符串规范成 'yyyy-MM-dd HH:mm:ss'。

    pydantic 默认把 datetime 序列化为 '2026-10-30T12:00:00'（含 T、微秒、可能时区），
    统一改成空格分隔、精确到秒；date-only（'yyyy-MM-dd'）不含 T，原样保留。
    """
    if isinstance(obj, dict):
        return {k: _normalize_datetimes(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return type(obj)(_normalize_datetimes(v) for v in obj)  # type: ignore[call]
    if isinstance(obj, str):
        if _ISO_DT_RE.match(obj):
            s = obj.replace("T", " ").replace("Z", "")
            s = re.sub(r"[+-]\d{2}:?\d{2}$", "", s)  # 去掉末尾时区偏移
            dot = s.find(".")
            if dot != -1:
                s = s[:dot]  # 去掉微秒，精确到秒
            return s
    return obj


class DatetimeJSONResponse(JSONResponse):
    """统一 API JSON 中 datetime 的展示格式为 'yyyy-MM-dd HH:mm:ss'。"""

    def render(self, content: Any) -> bytes:
        return super().render(_normalize_datetimes(content))


class ApiResponse(BaseModel, Generic[T]):
    """统一响应信封：{"code":0,"msg":"","data": <T>}。泛型 T 描述 data 结构。"""

    code: int = 0
    msg: str = ""
    data: T | None = None


def success(data: T | None = None, msg: str = "") -> "ApiResponse[T]":
    return ApiResponse(code=0, msg=msg, data=data)


def fail(code: int, msg: str, data: Any = None) -> ApiResponse:
    return ApiResponse(code=code, msg=msg, data=data)
