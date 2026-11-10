"""SQL 访问层：运行时只用 text() 写显式 SQL，不经过 ORM 映射。"""

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


_PAGE_SIZE_MAX = 200


async def fetch_page(
    session: AsyncSession,
    list_stmt: Executable,
    count_stmt: Executable,
    params: Mapping[str, Any] | None = None,
    *,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[dict[str, Any]], int]:
    """分页查询；list_stmt 声明 :limit/:offset，count_stmt 复用同一组过滤参数。"""
    if not isinstance(page, int) or page < 1:
        raise ValueError("page 必须是 >= 1 的整数")
    if not isinstance(page_size, int) or not 1 <= page_size <= _PAGE_SIZE_MAX:
        raise ValueError(f"page_size 必须是 1..{_PAGE_SIZE_MAX} 的整数")

    filters = dict(params or {})
    if "limit" in filters or "offset" in filters:
        raise ValueError("params 不得包含 limit/offset")
    rows = await fetch_all(
        session,
        list_stmt,
        {**filters, "limit": page_size, "offset": (page - 1) * page_size},
    )
    total = await fetch_value(session, count_stmt, filters)
    return rows, int(total or 0)


__all__ = [
    "execute_write",
    "fetch_all",
    "fetch_one",
    "fetch_page",
    "fetch_value",
    "session_scope",
]
