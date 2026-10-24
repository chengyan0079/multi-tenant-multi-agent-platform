"""Milvus 客户端对象（AsyncMilvusClient + 建库）。

连接 URI 由 host/port 拼装（该拼装原先写在 manager 内，已下沉到本类）。
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pymilvus import AsyncMilvusClient

from backend.common.logger import logger
from backend.data.clients.base import BaseClient, ClientError

if TYPE_CHECKING:
    from backend.config.schemas import MilvusSettings


class MilvusClient(BaseClient):
    """库级 Milvus 客户端。"""

    name = "milvus"

    def __init__(self, uri: str, db_name: str, token: str | None = None) -> None:
        self._uri = uri
        self._db_name = db_name
        self._token = token or None
        self._client: AsyncMilvusClient | None = None

    @classmethod
    def from_settings(cls, cfg: "MilvusSettings") -> "MilvusClient":
        return cls(cls.build_uri(cfg.host, cfg.port), db_name=cfg.db_name, token=cfg.token)

    @staticmethod
    def build_uri(host: str, port: int) -> str:
        """由 host/port 拼装连接 URI。"""
        return f"http://{host}:{port}"

    # ---------- 生命周期 ----------
    @property
    def is_connected(self) -> bool:
        return self._client is not None

    async def connect(self) -> None:
        if self._client is None:
            self._client = AsyncMilvusClient(
                uri=self._uri, db_name=self._db_name, token=self._token
            )

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()
        self._client = None

    # ---------- 能力 ----------
    @property
    def raw(self) -> AsyncMilvusClient:
        if self._client is None:
            raise ClientError("MilvusClient 未连接，请先 await connect()")
        return self._client

    async def ensure_database(self, db_name: str | None = None) -> None:
        """确保数据库存在（缺失则创建）。

        使用一次性 admin 客户端，用完即关，不占用业务实例。
        """
        target = db_name or self._db_name
        admin: Any = AsyncMilvusClient(uri=self._uri)
        try:
            existing = await admin.list_databases()
            if target in existing:
                logger.info(f"Milvus 数据库已存在: {target}")
            else:
                await admin.create_database(target)
                logger.info(f"已创建 Milvus 数据库: {target}")
        finally:
            await admin.close()
