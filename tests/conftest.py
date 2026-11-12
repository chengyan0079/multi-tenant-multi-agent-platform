"""共享测试基座。

提供真实 PostgreSQL 夹具：当环境变量 TEST_DATABASE_URL 未配置时，依赖它的测试会
优雅跳过（本仓无 sqlite 替代——ORM 运行时 SQL 含 PG 专属 NOW()/CAST(...AS JSON)/
uuid_generate_v4()，见统一咨询设计方案 §16.1 遗留项）。P7 真实回归应在 CI / 本地 PG 下运行。

与运行态一致的关键点（backend/data/clients/postgres.py:180）：
- 连接通过 server_settings 注入 search_path，使裸 SQL 解析到业务专属 schema（默认 unified_schemas）；
- 业务表 server_default 用到 uuid_generate_v4()，需 uuid-ossp 扩展；
- ORM 模型不在表上硬编码 schema，故 create_all 依赖 search_path 决定建表位置。

安全提示：TEST_DATABASE_URL 必须指向**专用测试库**。本夹具仅做幂等建表（create_all），
不在会话结束时 drop_all，避免误删共享库。
"""
from __future__ import annotations

import asyncio
import os

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL", "")
# 业务专属 schema（与运行态 postgres.search_path 一致）
TEST_DATABASE_SCHEMA = os.getenv("TEST_DATABASE_SCHEMA", "unified_schemas")


@pytest.fixture(scope="session")
def pg_url() -> str:
    if not TEST_DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL 未配置：跳过真实 PG 回归（CI / 本地 PG 下运行）")
    return TEST_DATABASE_URL


@pytest.fixture(scope="session")
def _pg_engine():
    if not TEST_DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL 未配置：跳过真实 PG 回归（CI / 本地 PG 下运行）")
    engine = create_async_engine(
        TEST_DATABASE_URL,
        future=True,
        connect_args={"server_settings": {"search_path": TEST_DATABASE_SCHEMA}},
    )
    # 注册全部 ORM 模型，确保 Base.metadata 含待建表（模型仅用于生成 DDL，运行期不查 ORM）
    import backend.data.postgres.agent.unified_turn  # noqa: F401
    import backend.data.postgres.business.meta  # noqa: F401

    from backend.data.postgres.base import Base

    async def _prepare() -> None:
        async with engine.begin() as conn:
            await conn.execute(
                text(f'CREATE SCHEMA IF NOT EXISTS "{TEST_DATABASE_SCHEMA}"')
            )
            await conn.execute(text('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"'))
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_prepare())
    yield engine
    asyncio.run(engine.dispose())


@pytest_asyncio.fixture
async def pg_session(_pg_engine):
    """真实 PG 会话：测试结束回滚，保证用例间互不污染。"""
    maker = async_sessionmaker(_pg_engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
