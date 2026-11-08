"""OpenAPI 生成回归测试。

路由函数的返回注解若写成 `Dict[str, Any]` 而模块里没导入 `Dict`，
`from __future__ import annotations` 会把它留成无法解析的 ForwardRef，
生成 `/openapi.json` 时抛 PydanticUserError（页面直接 500）。
这里生成一次文档，把这类注解问题挡在测试阶段。
"""
from __future__ import annotations

from fastapi import FastAPI

from backend.api.router import api_router


def test_openapi_schema_generates() -> None:
    """能生成完整 schema，且会话路由都在文档里。"""
    app = FastAPI()
    app.include_router(api_router)

    schema = app.openapi()

    paths = schema["paths"]
    assert "/api/v1/tenant/qa/sessions" in paths
    assert "/api/v1/tenant/orchestrator/resume" in paths
