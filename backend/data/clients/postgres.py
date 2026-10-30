"""PostgreSQL 客户端对象（engine + sessionmaker，实例内缓存）。

与旧实现的关键差异：
- url 由调用方显式传入（旧版隐式读 app_state.settings）→ 可同时持有多个实例（多库 / 灰度）；
- engine 与 sessionmaker 缓存于实例内（旧版是模块级全局），close 后不会静默重建。
"""
from __future__ import annotations

import re
import time
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, AsyncIterator

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from backend.common.logger import get_logger
from backend.data.clients.base import BaseClient, ClientError

if TYPE_CHECKING:
    from backend.config.schemas import PostgresSettings

# SQL 调试日志用的 logger（已带 trace_id；DEBUG 级别默认不输出，需把日志级别调到 DEBUG）
_sql_log = get_logger("db.sql")

# 三种占位符风格：asyncpg 的位置 $1、psycopg2 的位置 %s、命名 :name
_DOLLAR_RE = re.compile(r"\$(\d+)")
_PERCENT_RE = re.compile(r"%s")
_NAMED_RE = re.compile(r":(\w+)")

# 单参数内联后最大长度，超出截断，避免超长文本（chunk / 长 prompt）刷屏
_MAX_PARAM_LEN = 500


def _literal(v: Any) -> str:
    """把 Python 值渲染成 SQL 字面量（字符串加引号并转义单引号）。"""
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, (int, float)):
        return str(v)
    s = str(v)
    if len(s) > _MAX_PARAM_LEN:
        s = s[:_MAX_PARAM_LEN] + "...(truncated)"
    return "'" + s.replace("'", "''") + "'"


def _inline_params(statement: Any, parameters: Any) -> str:
    """把执行参数内联进 SQL 语句，得到可直接复制执行的真实语句。

    statement 在 before_cursor_execute 阶段已是编译后的字符串：asyncpg 用 $1 风格、
    psycopg2 用 %s、命名参数用 :name。按风格把参数值替换进去。
    """
    stmt = str(statement)
    if not parameters:
        return stmt
    if isinstance(parameters, dict):
        return _NAMED_RE.sub(lambda m: _literal(parameters.get(m.group(1))), stmt)
    params = list(parameters)
    if "$" in stmt:
        return _DOLLAR_RE.sub(lambda m: _literal(params[int(m.group(1)) - 1]), stmt)
    if "%s" in stmt:
        idx = 0

        def _pos(m: "re.Match[str]") -> str:
            nonlocal idx
            val = params[idx]
            idx += 1
            return _literal(val)

        return _PERCENT_RE.sub(_pos, stmt)
    return stmt


# 记录每条 SQL 的起始时间（按 ExecutionContext id 关联；ExecutionContext 用 __slots__，
# 不能随便 setattr，故用 id 映射，after 事件消费后弹出）
_START_TIMES: dict[int, float] = {}


def _row_count(cursor: Any, is_select: bool) -> int:
    """取执行影响 / 返回行数。

    写操作（INSERT/UPDATE/DELETE）cursor.rowcount 可靠；SELECT 在 asyncpg 下
    rowcount 恒为 -1，best-effort 用 asyncpg 内部的 pgresult.ntuples 拿真实返回行数，
    拿不到则回退 -1（仅调试日志，不影响主链路）。
    """
    rc = getattr(cursor, "rowcount", -1)
    if is_select and (rc is None or rc < 0):
        pgresult = getattr(cursor, "pgresult", None)
        if pgresult is not None:
            try:
                ntuples = pgresult.ntuples
                rc = ntuples() if callable(ntuples) else ntuples
            except Exception:  # noqa: BLE001 - asyncpg 内部 API 不稳定时回退
                pass
    return rc if rc is not None else -1


def _on_cursor_execute_before(
    conn: Any, cursor: Any, statement: Any, parameters: Any,
    context: Any, executemany: bool,
) -> None:
    _START_TIMES[id(context)] = time.perf_counter()


def _on_cursor_execute_after(
    conn: Any, cursor: Any, statement: Any, parameters: Any,
    context: Any, executemany: bool,
) -> None:
    """SQLAlchemy after_cursor_execute 事件：补耗时与返回值数量，打到 DEBUG 日志。

    批量（executemany）只记语句本身，不内联多行参数，避免刷屏。
    """
    t0 = _START_TIMES.pop(id(context), None)
    elapsed_ms = (time.perf_counter() - t0) * 1000 if t0 is not None else 0.0
    rows = _row_count(cursor, bool(getattr(context, "is_select", False)))
    if executemany:
        _sql_log.debug("SQL[executemany]: {} | {:.2f}ms | rows={}", statement, elapsed_ms, rows)
        return
    try:
        rendered = _inline_params(statement, parameters)
    except Exception:  # noqa: BLE001 - 渲染失败也不应影响主链路
        rendered = f"{statement} | params={parameters}"
    _sql_log.debug("SQL: {} | {:.2f}ms | rows={}", rendered, elapsed_ms, rows)


class PostgresClient(BaseClient):
    """PostgreSQL 异步引擎客户端。"""

    name = "postgres"

    def __init__(
        self, url: str, *, echo: bool = False, search_path: str | None = None,
        sql_debug: bool = False,
    ) -> None:
        self._url = url
        self._echo = echo
        self._search_path = search_path
        self._sql_debug = sql_debug
        self._engine: AsyncEngine | None = None
        self._sessionmaker: async_sessionmaker[AsyncSession] | None = None

    @classmethod
    def from_settings(cls, cfg: "PostgresSettings", *, echo: bool = False) -> "PostgresClient":
        """按配置构造（配置由调用方读取并传入，保持本类无全局依赖）。

        sql_debug 直接取配置（POSTGRES_SQL_DEBUG），所有 PG 实例统一受控。
        """
        return cls(
            cfg.async_url, echo=echo, search_path=cfg.search_path, sql_debug=cfg.sql_debug,
        )

    # ---------- 生命周期 ----------
    @property
    def is_connected(self) -> bool:
        return self._engine is not None

    async def connect(self) -> None:
        """创建 engine（幂等）。"""
        if self._engine is None:
            connect_args: dict = {}
            if self._search_path:
                # asyncpg 通过 server_settings 在建立连接时注入 search_path，
                # 使裸 SQL 默认解析到专属 schema（如 agent_platform）
                connect_args["server_settings"] = {"search_path": self._search_path}
            self._engine = create_async_engine(
                self._url, echo=self._echo, future=True, connect_args=connect_args
            )
            self._sessionmaker = async_sessionmaker(self._engine, expire_on_commit=False)
            # SQL 调试：仅在开启时挂事件（默认关，零开销）；事件走本项目 DEBUG 日志
            if self._sql_debug:
                event.listen(self._engine.sync_engine, "before_cursor_execute", _on_cursor_execute_before)
                event.listen(self._engine.sync_engine, "after_cursor_execute", _on_cursor_execute_after)

    async def close(self) -> None:
        """释放 engine（幂等）。"""
        if self._engine is not None:
            await self._engine.dispose()
        self._engine = None
        self._sessionmaker = None

    async def health_check(self) -> bool:
        """真实探活（SELECT 1），未连接返回 False。"""
        if self._engine is None:
            return False
        async with self._engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True

    # ---------- 能力 ----------
    @property
    def engine(self) -> AsyncEngine:
        if self._engine is None:
            raise ClientError("PostgresClient 未连接，请先 await connect()")
        return self._engine

    @property
    def raw(self) -> AsyncEngine:
        return self.engine

    @property
    def sessionmaker(self) -> async_sessionmaker[AsyncSession]:
        if self._sessionmaker is None:
            raise ClientError("PostgresClient 未连接，请先 await connect()")
        return self._sessionmaker

    @asynccontextmanager
    async def session_scope(self) -> AsyncIterator[AsyncSession]:
        """事务作用域会话。"""
        async with self.sessionmaker() as session:
            yield session
