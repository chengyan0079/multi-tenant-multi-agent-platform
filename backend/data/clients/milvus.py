"""Milvus 客户端：AsyncMilvusClient 封装 + 建库 + 集合生命周期，字段参数由调用方注入。"""

from __future__ import annotations

import functools
import inspect
import time
from typing import TYPE_CHECKING, Any

from pymilvus import AsyncMilvusClient, CollectionSchema

from backend.common.logger import brief, brief_args, logger
from backend.data.clients.base import BaseClient, ClientError

if TYPE_CHECKING:
    from backend.config.schemas import MilvusSettings


class _LoggedMilvus:
    """AsyncMilvusClient 的读写日志代理。

    所有集合/数据读写方法（upsert / hybrid_search / search / query / get / delete /
    has_collection / create_collection / load_collection …）都是协程，统一在此打 debug；
    prepare_index_params 等同步方法原样透传，避免破坏返回类型。
    """

    def __init__(self, inner: AsyncMilvusClient) -> None:
        self._inner = inner

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._inner, name)
        if not callable(attr) or not inspect.iscoroutinefunction(attr):
            return attr

        @functools.wraps(attr)
        async def _call(*args: Any, **kwargs: Any) -> Any:
            logger.debug(f"[milvus] → {name} args={brief_args(args, kwargs)}")
            started = time.perf_counter()
            try:
                result = await attr(*args, **kwargs)
            except Exception as exc:
                cost = (time.perf_counter() - started) * 1000
                logger.debug(f"[milvus] ✗ {name} cost={cost:.1f}ms error={brief(str(exc))}")
                raise
            cost = (time.perf_counter() - started) * 1000
            logger.debug(f"[milvus] ← {name} cost={cost:.1f}ms result={brief(result)}")
            return result

        return _call


class MilvusClient(BaseClient):
    """库级 Milvus 客户端。

    connect() 是惰性建连（pymilvus 在首次 IO 才真正握手），因此 connect 成功不代表可达，
    请用 health_check()/verify() 做真实探活（尤其启动时）。
    """

    name = "milvus"

    def __init__(self, uri: str, db_name: str, token: str | None = None) -> None:
        self._uri = uri
        self._db_name = db_name
        self._token = token or None
        self._client: AsyncMilvusClient | None = None
        self._logged: _LoggedMilvus | None = None

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
            self._logged = _LoggedMilvus(self._client)

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()
        self._client = None
        self._logged = None

    async def health_check(self) -> bool:
        """真实探活：能列出数据库才视为健康。

        基类的默认实现只看对象是否非空，会误判（惰性连接其实没握手）。
        """
        try:
            await self.raw.list_databases()
            return True
        except Exception:  # noqa: BLE001 - 探活失败即不健康
            return False

    async def verify(self) -> None:
        """确保已连接且可通信，否则抛 ClientError（供 manager 启动时强校验）。"""
        if not self.is_connected:
            raise ClientError("MilvusClient 未连接，请先 await connect()")
        if not await self.health_check():
            raise ClientError("Milvus 连接探活失败（地址/端口/凭据或网络不可达）")

    # ---------- 能力 ----------
    @property
    def raw(self) -> AsyncMilvusClient:
        """返回带读写 debug 日志的代理；行为与 AsyncMilvusClient 一致。

        代理对协程方法记录参数/结果摘要与耗时，同步方法（prepare_index_params 等）
        原样透传。所有业务调用方（DocumentMilvusStore / app_state.milvus_client）
        都从这里取客户端，故无需在业务侧散落日志代码。
        """
        if self._client is None or self._logged is None:
            raise ClientError("MilvusClient 未连接，请先 await connect()")
        return self._logged  # type: ignore[return-value]

    async def ensure_database(self, db_name: str | None = None) -> None:
        """确保数据库存在（缺失则创建）。

        使用一次性 admin 客户端（连默认库），用完即关，不占用业务实例连接。
        """
        target = db_name or self._db_name
        admin: Any = _LoggedMilvus(AsyncMilvusClient(uri=self._uri))
        try:
            existing = await admin.list_databases()
            if target in existing:
                logger.info(f"Milvus 数据库已存在: {target}")
            else:
                await admin.create_database(target)
                logger.info(f"已创建 Milvus 数据库: {target}")
        finally:
            await admin.close()

    # ---------- 集合生命周期（schema / 索引参数由调用方注入，RAG 文档集合见 DocumentMilvusStore） ----------
    async def has_collection(self, name: str) -> bool:
        return await self.raw.has_collection(name)

    async def drop_collection(self, name: str) -> None:
        if await self.has_collection(name):
            await self.raw.drop_collection(name)

    async def create_collection(
        self,
        name: str,
        schema: CollectionSchema,
        index_params: Any,
        *,
        drop_if_exists: bool = False,
    ) -> None:
        """创建集合并建立索引。

        drop_if_exists=True 时先删后建（危险，仅初始化 / 迁移脚本使用）；
        默认 False，已存在则抛错以防误覆盖。
        """
        if drop_if_exists:
            await self.drop_collection(name)
        await self.raw.create_collection(name, schema=schema, index_params=index_params)

    async def load_collection(self, name: str) -> None:
        await self.raw.load_collection(name)

    async def release_collection(self, name: str) -> None:
        await self.raw.release_collection(name)

    async def ensure_collection(
        self,
        name: str,
        schema: CollectionSchema,
        index_params: Any,
        *,
        drop_if_exists: bool = False,
    ) -> bool:
        """确保集合就绪：不存在则建集合 + 索引并加载；已存在则直接加载。幂等，适合启动时调用。

        返回 True 表示本次新建了集合；False 表示已存在、仅执行了加载。
        """
        existed = await self.has_collection(name)
        if existed:
            if drop_if_exists:
                await self.drop_collection(name)
            else:
                await self.load_collection(name)
                return False
        await self.create_collection(name, schema, index_params, drop_if_exists=drop_if_exists)
        await self.load_collection(name)
        return True

    # ---------- 异步上下文管理 ----------
    async def __aenter__(self) -> "MilvusClient":
        await self.connect()
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        await self.close()
