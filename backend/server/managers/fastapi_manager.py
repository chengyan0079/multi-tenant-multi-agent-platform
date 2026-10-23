"""FastAPI 装配：挂载 routers + 中间件 + SSE。"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend.api.v1 import (
    config_center,
    escalations,
    interview_router,
    exam_router,
    orchestrator,
    plugins,
    qa_router,
    resume_router,
    threads,
    unified_chat,
)
from backend.api.exceptions import register_exception_handlers
from backend.app_state import app_state
from backend.middleware.api_log import ApiLogMiddleware
from backend.middleware.rate_limit import limiter
from backend.middleware.trace_id import TraceIdMiddleware
from backend.server.base_manager import BaseManager


def _build_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield

    app = FastAPI(title=app_state.settings.app_name, lifespan=lifespan)
    app.state.limiter = limiter
    app.add_middleware(ApiLogMiddleware)
    app.add_middleware(TraceIdMiddleware)
    # 认证依赖在路由层按需声明（Depends(get_current_user)），不做全局强制
    for r in (
        unified_chat.router,
        resume_router,
        qa_router,
        exam_router,
        interview_router,
        orchestrator.router,
        threads.router,
        plugins.router,
        escalations.router,
        config_center.router,
    ):
        app.include_router(r)
    register_exception_handlers(app)
    return app


class FastAPIManager(BaseManager):
    async def start(self) -> None:
        app_state.fastapi_app = _build_app()

    async def stop(self) -> None:
        app_state.fastapi_app = None
