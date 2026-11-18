"""MCP Server Manager：把 web_search FastMCP Server 挂载到本进程 FastAPI。"""
from __future__ import annotations

from backend.app_state import app_state
from backend.tools.web_search_server import web_search_mcp
from backend.server.base_manager import BaseManager, HealthInfo


class MCPServerManager(BaseManager):
    """独立管理 MCP Server 生命周期；依赖 FastAPIManager 先建好 app。"""

    def __init__(self) -> None:
        super().__init__()
        self._mounted = False

    async def start(self) -> None:
        app = app_state.fastapi_app
        if app is None:
            raise RuntimeError("FastAPI 未装配，无法挂载 MCP Server")
        app.mount(
            "/mcp/web-search",
            web_search_mcp.http_app(stateless_http=True, json_response=True),
        )
        self._mounted = True

    async def stop(self) -> None:
        # mount 随 FastAPI app 销毁，无需显式卸载
        self._mounted = False

    async def health(self) -> HealthInfo:
        return HealthInfo(
            status="running" if self._mounted else "down",
            detail="web_search MCP Server 已挂载" if self._mounted else "未挂载",
        )
