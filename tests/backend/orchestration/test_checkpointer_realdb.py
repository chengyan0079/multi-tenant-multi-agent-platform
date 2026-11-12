"""Step 4 真实 PG 回归：AsyncPostgresSaver 真实写入/读取往返（R19 / P0）。

仅 mock DB 连接的 search_path，checkpointer 全部走真实 PostgreSQL：pool 由 psycopg 建立，
AsyncPostgresSaver.setup() 建表、aput/aget 完成往返。需 TEST_DATABASE_URL。无 PG 环境下跳过。

构造方式与运行态 checkpointer_manager.start 同构（psycopg AsyncConnectionPool + server_settings）。
"""
from __future__ import annotations

import os

import pytest
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg_pool import AsyncConnectionPool

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="需 TEST_DATABASE_URL 真实 PG（checkpointer 真实读写往返）",
)

SCHEMA = os.getenv("TEST_DATABASE_SCHEMA", "unified_schemas")


async def _configure(conn) -> None:
    await conn.execute(f'SET search_path TO "{SCHEMA}"')


async def test_checkpointer_roundtrip(_pg_engine, pg_url: str) -> None:
    dsn = pg_url.replace("+asyncpg", "")
    pool = AsyncConnectionPool(
        conninfo=dsn,
        open=False,
        configure=_configure,
        reset=_configure,
        kwargs={"autocommit": True, "prepare_threshold": 0},
        min_size=1,
        max_size=4,
    )
    await pool.open()
    try:
        saver = AsyncPostgresSaver(conn=pool)
        await saver.setup()  # 幂等建 checkpoint_* 表
        config = {"configurable": {"thread_id": "ckpt-rt-1"}}
        await saver.aput(config, {"question": "1+1=", "answer": "2"})
        loaded = await saver.aget(config)
        assert loaded is not None
        # langgraph 返回 CheckpointTuple，channel_values 承载写入的键值
        assert loaded.channel_values["answer"] == "2"
    finally:
        await pool.close()
