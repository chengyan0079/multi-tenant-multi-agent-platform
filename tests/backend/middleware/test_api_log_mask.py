"""api_log 中间件：请求参数脱敏纯函数单测（不启动服务）。

验证 body 里的敏感字段（password/token/secret...）被替换成 ***，且非 JSON 文本、
列表、嵌套结构都正确处理；非敏感字段原样保留。
"""
from __future__ import annotations

from backend.middleware.api_log import _mask_body, _safe_json


def test_mask_body_hides_password_and_token() -> None:
    data = {
        "username": "admin",
        "password": "s3cret",
        "token": "abc.def",
        "scope": "unified:ask",
    }
    out = _mask_body(data)
    assert out["password"] == "***"
    assert out["token"] == "***"
    assert out["username"] == "admin"
    assert out["scope"] == "unified:ask"


def test_mask_body_recurses_into_nested_and_list() -> None:
    data = {
        "items": [{"secret": "x"}, {"name": "ok"}],
        "profile": {"old_password": "p1", "email": "a@b.c"},
    }
    out = _mask_body(data)
    assert out["items"][0]["secret"] == "***"
    assert out["items"][1]["name"] == "ok"
    assert out["profile"]["old_password"] == "***"
    assert out["profile"]["email"] == "a@b.c"


def test_safe_json_passthrough_non_json() -> None:
    assert _safe_json("username=admin&password=123") == "username=admin&password=123"
    assert _safe_json("") == ""
    assert _safe_json('{"a":1}') == {"a": 1}
