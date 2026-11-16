"""sql_exec_sandbox：在沙箱（env=sandbox）执行已审批变更单的 SQL。

安全设计（防注入 / 防"假分析真执行"）：
- **不接受外部 SQL 入参**，SQL 只从 `agent_change_request`（且 status=approved）读取；
- 仅允许 `env=sandbox` 的连接，prod 一律拒绝；
- 单语句、禁事务控制（sqlglot 判定）；
- 即用即弃：PG 事务执行后 ROLLBACK；MySQL DML 事务后 ROLLBACK；MySQL DDL 不可回滚 → 拒绝真执行（validate_only）。
"""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy import text

from backend.common.logger import get_logger
from backend.data.dao.agent.db_connection_dao import DbConnectionDao
from backend.data.sql import fetch_one, session_scope
from backend.mcp.protocol import BaseTool
from backend.services.sql_script_service import analyze_sql

logger = get_logger("sql_exec_sandbox")


def _dsn_pg(c: dict) -> str:
    return (
        f"postgresql://{c['username']}:{c['password']}@"
        f"{c['host']}:{c['port']}/{c['database']}"
    )


def _affected(status: str | None) -> int:
    """从执行状态解析影响行数（如 'UPDATE 5'）。"""
    if not status:
        return 0
    last = status.strip().split()[-1] if status.strip() else ""
    return int(last) if last.isdigit() else 0


class SqlExecSandboxTool(BaseTool):
    name = "sql_exec_sandbox"
    description = "在沙箱(env=sandbox)执行已审批变更单SQL；不接受外部SQL；PG事务回滚/MySQL仅DML事务"

    async def run(self, **kwargs: Any) -> dict:
        tenant_id = int(kwargs.get("tenant_id") or 0)
        request_id = int(kwargs.get("request_id") or 0)
        connection_id = str(kwargs.get("connection_id") or "")
        execute = bool(kwargs.get("execute", True))

        if not connection_id:
            return {"ok": False, "error": "缺少 connection_id"}
        conn = await DbConnectionDao.get(tenant_id, connection_id)
        if conn is None:
            return {"ok": False, "error": "数据源不存在或无权访问"}
        if (conn.get("env") or "prod") != "sandbox":
            return {"ok": False, "error": "仅允许 env=sandbox 的连接执行"}

        async with session_scope() as session:
            req = await fetch_one(
                session,
                text(
                    "SELECT sql_text, status FROM agent_change_request "
                    "WHERE tenant_id = :t AND id = :id"
                ),
                {"t": tenant_id, "id": request_id},
            )
        if req is None:
            return {"ok": False, "error": "变更单不存在"}
        if (req.get("status") or "") != "approved":
            return {"ok": False, "error": "变更单未审批通过，禁止执行"}

        sql = req.get("sql_text") or ""
        db_type = (conn.get("db_type") or "").lower()
        info = analyze_sql(sql, db_type)
        if not info.get("ok"):
            return {"ok": False, "error": "SQL 不合法", "detail": info.get("errors")}
        if len(info.get("kinds") or []) > 1:
            return {"ok": False, "error": "仅支持单条语句"}
        if info.get("kind") == "txn":
            return {"ok": False, "error": "不支持事务控制语句"}

        if not execute:
            return {"ok": True, "mode": "validate_only", "exec_ok": None, "rolled_back": None}

        if db_type in ("postgresql", "postgres", "pg"):
            return await self._pg_exec(conn, sql)
        if db_type == "mysql":
            if info.get("kind") == "ddl":
                # MySQL DDL 隐式提交不可回滚，沙箱真执行会残留 → 拒绝，降级为只校验
                return {
                    "ok": False,
                    "mode": "validate_only",
                    "error": "MySQL DDL 不可事务回滚，已拒绝真执行（改为校验模式）",
                }
            return await self._mysql_exec(conn, sql)
        return {"ok": False, "error": f"不支持的 db_type: {db_type}"}

    async def _pg_exec(self, conn: dict, sql: str) -> dict:
        import asyncpg

        start = time.monotonic()
        c = await asyncpg.connect(_dsn_pg(conn), timeout=float(conn.get("timeout", 10)))
        try:
            tr = c.transaction()
            await tr.start()
            try:
                status = await c.execute(sql)
            finally:
                await tr.rollback()
            return {
                "ok": True,
                "mode": "execute",
                "exec_ok": True,
                "exec_ms": int((time.monotonic() - start) * 1000),
                "affected_rows": _affected(status),
                "rolled_back": True,
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"pg 沙箱执行失败: {exc}")
            return {
                "ok": True,
                "mode": "execute",
                "exec_ok": False,
                "exec_ms": int((time.monotonic() - start) * 1000),
                "error": str(exc),
                "rolled_back": True,
            }
        finally:
            await c.close()

    async def _mysql_exec(self, conn: dict, sql: str) -> dict:
        import aiomysql

        start = time.monotonic()
        c = await aiomysql.connect(
            host=conn["host"],
            port=int(conn["port"]),
            user=conn["username"],
            password=conn["password"],
            db=conn["database"],
            connect_timeout=int(conn.get("timeout", 10)),
            autocommit=False,
        )
        try:
            async with c.cursor() as cur:
                try:
                    await cur.execute(sql)
                    affected = cur.rowcount
                finally:
                    await c.rollback()
            return {
                "ok": True,
                "mode": "execute",
                "exec_ok": True,
                "exec_ms": int((time.monotonic() - start) * 1000),
                "affected_rows": int(affected or 0),
                "rolled_back": True,
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"mysql 沙箱执行失败: {exc}")
            return {
                "ok": True,
                "mode": "execute",
                "exec_ok": False,
                "exec_ms": int((time.monotonic() - start) * 1000),
                "error": str(exc),
                "rolled_back": True,
            }
        finally:
            c.close()
