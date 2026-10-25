"""
main - 入口：装配 AppServer().run()

启动顺序由 register() 决定（order 0→100）；停机逆序释放。HTTP 由 uvicorn 拉起，引用 app_state.fastapi_app。
"""
from __future__ import annotations

import asyncio

import uvicorn

from backend.app_state import app_state
from backend.common.logger import get_logger
from backend.config import config as app_config
from backend.server.app_server import StartupError
from backend.server.register import build_server


async def _serve() -> None:
    server = build_server()
    # 让 /health 等运维接口能拿到 AppServer 汇总各组件状态
    app_state.server = server
    try:
        await server.start_all()
    except StartupError as exc:
        get_logger("main").error(f"启动失败: {exc}")
        raise SystemExit(1)
    # 启动后由 uvicorn 接管 HTTP；信号(SIGINT/SIGTERM)触发逆序 stop
    # 绑定地址/端口与 Nacos 注册身份统一引用 ServiceSettings（同一份配置）
    uv_config = uvicorn.Config(
        app_state.fastapi_app,
        host=app_config.service.ip,
        port=app_config.service.port,
        log_level=app_config.logging.level,
    )
    http_server = uvicorn.Server(uv_config)
    try:
        await http_server.serve()
    finally:
        await server.stop_all()


def main() -> None:
    asyncio.run(_serve())


if __name__ == "__main__":
    main()
