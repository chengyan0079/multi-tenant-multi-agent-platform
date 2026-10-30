"""PostgresClient SQL 调试日志的纯函数单测（不连库、不依赖引擎）。

验证 before/after 事件协作产出的「耗时 + 返回值数量」以及参数内联渲染：
- 内联覆盖 asyncpg 的 $n、psycopg2 的 %s、命名 :name 三种风格；
- 值处理 None/bool/数字/字符串/超长截断；
- 写操作取 cursor.rowcount，SELECT 在 asyncpg 行数不可知时回退 -1（best-effort）；
- 批量（executemany）只记语句不内联。
"""
from __future__ import annotations

import backend.data.clients.postgres as m
from backend.data.clients.postgres import (
    _inline_params,
    _literal,
    _on_cursor_execute_after,
    _on_cursor_execute_before,
    _row_count,
)


def test_literal_scalars() -> None:
    assert _literal(None) == "NULL"
    assert _literal(True) == "TRUE"
    assert _literal(False) == "FALSE"
    assert _literal(3) == "3"
    assert _literal(1.5) == "1.5"
    assert _literal("a'b") == "'a''b'"


def test_literal_truncates_long_text() -> None:
    long = "x" * 600
    out = _literal(long)
    assert out.endswith("...(truncated)'")
    assert len(out) < 600 + 20


def test_inline_named_params() -> None:
    sql = "SELECT * FROM t WHERE id = :tid AND name = :nm"
    out = _inline_params(sql, {"tid": 1, "nm": "alice"})
    assert out == "SELECT * FROM t WHERE id = 1 AND name = 'alice'"


def test_inline_dollar_params_asyncpg() -> None:
    sql = "SELECT * FROM t WHERE id = $1 AND status = $2"
    out = _inline_params(sql, (7, "ok"))
    assert out == "SELECT * FROM t WHERE id = 7 AND status = 'ok'"


def test_inline_percent_params_psycopg2() -> None:
    sql = "INSERT INTO t (a, b) VALUES (%s, %s)"
    out = _inline_params(sql, ("x", None))
    assert out == "INSERT INTO t (a, b) VALUES ('x', NULL)"


def test_inline_no_params_returns_statement() -> None:
    assert _inline_params("SELECT 1", None) == "SELECT 1"
    assert _inline_params("SELECT 1", ()) == "SELECT 1"


class _FakeCursor:
    """模拟 DBAPI cursor：rowcount 可控，SELECT 时模拟 asyncpg 的 pgresult.ntuples。"""

    def __init__(self, rowcount: int, *, pg_ntuples: int | None = None) -> None:
        self.rowcount = rowcount
        self._pg_ntuples = pg_ntuples

    @property
    def pgresult(self) -> object:
        if self._pg_ntuples is None:
            raise AttributeError
        return type("PG", (), {"ntuples": self._pg_ntuples})()


def test_row_count_write_uses_rowcount() -> None:
    # 写操作：cursor.rowcount 可靠
    assert _row_count(_FakeCursor(3), is_select=False) == 3


def test_row_count_select_asyncpg_ntuples() -> None:
    # SELECT + asyncpg 内部 pgresult.ntuples 拿到真实返回行数
    assert _row_count(_FakeCursor(-1, pg_ntuples=12), is_select=True) == 12


def test_row_count_select_fallback_when_no_pgresult() -> None:
    # SELECT 且无 pgresult（非 asyncpg / 版本变动）：回退 -1
    assert _row_count(_FakeCursor(-1), is_select=True) == -1


def test_before_after_emits_sql_with_elapsed_and_rows() -> None:
    # before/after 协作：记录耗时、打印内联语句 + 行数；不消费结果集
    captured: dict = {}

    class _Log:
        def debug(self, msg: str, *a: object) -> None:
            captured["msg"] = msg.format(*a)

    saved = m._sql_log
    m._sql_log = _Log()  # type: ignore[assignment]
    try:
        ctx = type("Ctx", (), {"is_select": True})()
        _on_cursor_execute_before(None, None, "SELECT 1", (), ctx, False)
        _on_cursor_execute_after(
            None, _FakeCursor(-1, pg_ntuples=5), "SELECT 1", (), ctx, False
        )
    finally:
        m._sql_log = saved
    assert captured["msg"].startswith("SQL: SELECT 1 | ")
    assert "rows=5" in captured["msg"]
    assert "ms" in captured["msg"]


def test_after_executemany_skips_inline() -> None:
    captured: dict = {}

    class _Log:
        def debug(self, msg: str, *a: object) -> None:
            captured["msg"] = msg.format(*a)

    saved = m._sql_log
    m._sql_log = _Log()  # type: ignore[assignment]
    try:
        ctx = object()
        _on_cursor_execute_before(None, None, "UPDATE t SET x=$1", [(1,), (2,)], ctx, True)
        _on_cursor_execute_after(
            None, _FakeCursor(2), "UPDATE t SET x=$1", [(1,), (2,)], ctx, True
        )
    finally:
        m._sql_log = saved
    assert captured["msg"].startswith("SQL[executemany]: UPDATE t SET x=$1 | ")
    assert "rows=2" in captured["msg"]
    assert "ms" in captured["msg"]
