"""FastAPI 装配：挂载 routers + 中间件 + SSE + 可配置文档。"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend.api.router import api_router
from backend.api.exceptions import register_exception_handlers
from backend.app_state import app_state
from backend.common.response import DatetimeJSONResponse
from backend.middleware.api_log import ApiLogMiddleware
from backend.middleware.rate_limit import limiter
from backend.middleware.trace_id import TraceIdMiddleware
from backend.server.base_manager import BaseManager, HealthInfo


def _build_app() -> FastAPI:
    # 故意留空：资源启动/停机由 AppServer 按 order 编排各 Manager（start_all/stop_all），
    # 不在 FastAPI lifespan 里做。此处仅占位，避免 uvicorn 触发默认 startup 时与 AppServer
    # 的 manager 编排重复或竞争。因此本服务只能由 `python backend/main.py` 启动。
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield

    svc = app_state.settings.service
    # 通过 DOCS_ENABLED 配置控制 Swagger UI / ReDoc 是否暴露；生产环境默认关闭
    docs_url = "/docs" if svc.docs_enabled else None
    redoc_url = "/redoc" if svc.docs_enabled else None
    openapi_url = "/openapi.json" if svc.docs_enabled else None

    app = FastAPI(
        title=svc.name,
        version=svc.version,
        lifespan=lifespan,
        docs_url=docs_url,
        redoc_url=redoc_url,
        openapi_url=openapi_url,
        default_response_class=DatetimeJSONResponse,
    )
    app.state.limiter = limiter
    app.add_middleware(ApiLogMiddleware)
    app.add_middleware(TraceIdMiddleware)
    # 认证依赖在路由层按需声明（Depends(get_current_user)），不做全局强制
    app.include_router(api_router)
    register_exception_handlers(app)

    @app.get("/health", tags=["ops"], summary="健康检查（汇总各组件状态）")
    async def health() -> dict:
        # 探针接口不强制鉴权；AppServer 未就绪时降级返回 unknown
        srv = app_state.server
        if srv is None or not hasattr(srv, "health_report"):
            return {"status": "unknown", "components": []}
        return await srv.health_report()

    return app


class FastAPIManager(BaseManager):
    async def start(self) -> None:
        app_state.fastapi_app = _build_app()

    async def stop(self) -> None:
        app_state.fastapi_app = None

    async def health(self) -> HealthInfo:
        if app_state.fastapi_app is None:
            return HealthInfo(status="down", detail="fastapi app 未构建")
        return HealthInfo(status="running")
