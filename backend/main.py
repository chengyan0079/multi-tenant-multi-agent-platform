"""
main - 入口：装配 AppServer().run()

启动顺序由 register() 决定（order 0→100）；停机逆序释放。HTTP 由 uvicorn 拉起，引用 app_state.fastapi_app。
"""
from __future__ import annotations

import asyncio

import uvicorn

from backend.app_state import app_state
from backend.common.logger import get_logger
from backend.server.app_server import StartupError
from backend.server.register import build_server


async def _serve() -> None:
    server = build_server()
    try:
        await server.start_all()
    except StartupError as exc:
        get_logger("main").error(f"启动失败: {exc}")
        raise SystemExit(1)
    # 启动后由 uvicorn 接管 HTTP；信号(SIGINT/SIGTERM)触发逆序 stop
    config = uvicorn.Config(
        app_state.fastapi_app,
        host="0.0.0.0",
        port=8000,
        log_level="info",
    )
    http_server = uvicorn.Server(config)
    try:
        await http_server.serve()
    finally:
        await server.stop_all()


def main() -> None:
    asyncio.run(_serve())


if __name__ == "__main__":
    main()
