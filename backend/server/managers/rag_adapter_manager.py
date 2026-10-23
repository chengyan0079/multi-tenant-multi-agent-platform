"""rag-ultra 适配层初始化（复用，不重建）。"""
from __future__ import annotations

from backend.rag.client import client
from backend.server.base_manager import BaseManager


class RagAdapterManager(BaseManager):
    async def start(self) -> None:
        # 客户端惰性建立连接；此处仅确保可导入且配置存在
        if not (client._module or client._http):
            try:
                client._ensure()
            except Exception as exc:
                from backend.common.logger import get_logger

                get_logger("rag_adapter").warning(f"rag-ultra 未就绪(降级): {exc}")

    async def stop(self) -> None:
        await client.stop()
