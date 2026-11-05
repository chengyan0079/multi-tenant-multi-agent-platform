"""LangGraph checkpointer：用 psycopg 连接池跑 setup() 建表，状态外置。

注意：本版本 AsyncPostgresSaver 要的是 psycopg 连接（非 SQLAlchemy 引擎），且 setup()
是实例方法——需先构造一个绑定连接的 saver 再调用。建表统一落在业务同 schema
（config.postgres.search_path），避免与 ORM/DAO 的表分散在不同 schema 造成的读写错位。

用 AsyncConnectionPool 而非单连接：多 agent / 高并发下 checkpoint I/O 可并行，
避免单连接串行化瓶颈与单点故障。
"""
from __future__ import annotations

from psycopg import AsyncConnection
from psycopg_pool import AsyncConnectionPool

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from backend.app_state import app_state
from backend.config import config
from backend.server.base_manager import BaseManager, HealthInfo


async def _configure_conn(conn: AsyncConnection) -> None:
    """连接池内每条新连接都切到业务 schema（checkpoint_* 表与 ORM 表同 schema）。

    psycopg3 在连接归还时做 rollback（不清除 search_path 这类会话级 GUC），故建连时设一次即可；
    这里同时挂到 configure 与 reset 上，无论是否被调用都保证 search_path 正确。
    """
    await conn.execute(f"SET search_path TO {config.postgres.search_path}")


class CheckpointerManager(BaseManager):
    def __init__(self, name: str | None = None) -> None:
        super().__init__(name)
        # psycopg 连接池（与 SQLAlchemy 业务连接池分离）；stop() 时关闭
        self._pool: AsyncConnectionPool | None = None

    async def start(self) -> None:
        # SQLAlchemy 的 AsyncEngine 不能直接喂给 psycopg 版 saver；
        # 这里建一个 psycopg 连接池（DSN 去掉 +asyncpg 驱动标识），并切到业务 schema。
        dsn = str(config.postgres.async_url).replace("+asyncpg", "")
        self._pool = AsyncConnectionPool(
            conninfo=dsn,
            open=False,
            configure=_configure_conn,
            reset=_configure_conn,
            kwargs={"autocommit": True, "prepare_threshold": 0},
            min_size=2,
            max_size=10,
        )
        await self._pool.open()
        saver = AsyncPostgresSaver(conn=self._pool)
        await saver.setup()  # 幂等建表（checkpoint_migrations 等）
        app_state.checkpointer = saver

    async def stop(self) -> None:
        # saver 不持有连接：构造时传入的是我们自建的连接池（conn=self._pool），saver 仅借用连接，
        # 当前 langgraph 版本的 AsyncPostgresSaver 也无 aclose/close 方法，故无需单独释放 saver，
        # 直接关闭我们自己的连接池即可。
        app_state.checkpointer = None
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def health(self) -> HealthInfo:
        # 检查点状态外置在 PG，本组件无独立连接；仅校验实例是否就绪
        # （连通性由 PostgreSQLManager 探活）
        if app_state.checkpointer is None:
            return HealthInfo(status="down", detail="checkpointer 未初始化")
        return HealthInfo(status="running")
