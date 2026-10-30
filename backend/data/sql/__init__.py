"""SQL 访问层：运行时只用 text() 写显式 SQL，不经过 ORM 映射。

约定
- SQL 全部以模块级 `text()` 常量内联在 DAO 文件里，不读外部 .sql 文件；
- 查询结果统一转成 dict（列名 → 值），不构造实体对象；
- ORM 模型（backend/data/postgres）只服务于 scripts/gen_schema.py 生成 DDL，
  运行期不导入，避免表结构定义在代码里出现两份来源。
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Mapping

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Executable

from backend.app_state import app_state
from backend.data.clients.postgres import PostgresClient


def _postgres() -> PostgresClient:
    """取 PostgreSQL 客户端实例（未注册或未连接时报错并说明原因）。"""
    return app_state.clients.get_as("postgres", PostgresClient)


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """事务作用域会话：进入即开启事务，正常退出自动提交、异常退出自动回滚。

    统一用 SQLAlchemy 的 session.begin() 管理事务边界，替代各 DAO 散落的
    session.commit()。Nacos 这类外部调用放进本块内即可：调用成功→块退出提交，
    调用抛异常→块退出回滚。读操作同理，无副作用。
    """
    async with _postgres().session_scope() as session:
        async with session.begin():
            yield session


async def fetch_all(
    session: AsyncSession, stmt: Executable, params: Mapping[str, Any] | None = None
) -> list[dict[str, Any]]:
    """查询多行，返回 dict 列表（列名 → 值）。"""
    result = await session.execute(stmt, dict(params or {}))
    return [dict(row) for row in result.mappings().all()]


async def fetch_one(
    session: AsyncSession, stmt: Executable, params: Mapping[str, Any] | None = None
) -> dict[str, Any] | None:
    """查询单行，没有命中返回 None。"""
    result = await session.execute(stmt, dict(params or {}))
    row = result.mappings().first()
    return dict(row) if row is not None else None


async def fetch_value(
    session: AsyncSession, stmt: Executable, params: Mapping[str, Any] | None = None
) -> Any:
    """查询单个标量（COUNT / EXISTS / RETURNING 单列），没有命中返回 None。"""
    result = await session.execute(stmt, dict(params or {}))
    return result.scalar_one_or_none()


async def execute_write(
    session: AsyncSession, stmt: Executable, params: Mapping[str, Any] | None = None
) -> int:
    """执行写语句，返回受影响行数。"""
    result = await session.execute(stmt, dict(params or {}))
    return result.rowcount or 0


__all__ = [
    "execute_write",
    "fetch_all",
    "fetch_one",
    "fetch_value",
    "session_scope",
]
