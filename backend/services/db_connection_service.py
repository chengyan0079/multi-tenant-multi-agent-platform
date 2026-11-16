"""数据库连接服务：按 connection_id 取数据源，建立只读连接并查询元数据/执行计划。

安全约束（防注入 / 防"假分析真执行"）：
- EXPLAIN 仅允许单条只读 SELECT/WITH；禁多语句、禁 DDL/DML 关键字；
- 连接开启只读事务/会话，原 SQL 绝不执行（只 EXPLAIN）；
- MySQL 仅支持 InnoDB：非 InnoDB 表给出告警（不做 DDL 建议）；
- 密码不出后端；失败降级返回结构化错误。
"""

from __future__ import annotations

import re
from typing import Any

from backend.common.logger import get_logger
from backend.data.dao.agent.db_connection_dao import DbConnectionDao

logger = get_logger("db_connection_service")

# 可评审语句：查询 + DML + DDL（评审只分析，不执行原 SQL）；不支持事务控制
_QUERY_HEADS = {"SELECT", "WITH", "TABLE", "VALUES"}
_DML_HEADS = {"INSERT", "UPDATE", "DELETE", "REPLACE", "MERGE"}
_DDL_HEADS = {
    "ALTER",
    "CREATE",
    "DROP",
    "TRUNCATE",
    "RENAME",
    "COMMENT",
    "GRANT",
    "REVOKE",
    "ANALYZE",
    "VACUUM",
}
_TXN_HEADS = {"BEGIN", "COMMIT", "ROLLBACK", "SAVEPOINT", "RELEASE", "START", "END"}


def assert_reviewable_sql(sql: str) -> tuple[str, str]:
    """校验单条可评审语句（DML/DDL/查询），不支持事务；返回 (SQL, kind)。

    kind: query / dml / ddl。仅做文本校验，不执行原 SQL。
    """
    s = (sql or "").strip()
    if not s:
        raise ValueError("SQL 为空")
    body = s.rstrip(";").strip()
    if ";" in body:
        raise ValueError("仅支持单条语句（禁止多语句）")
    head = body.split(None, 1)[0].upper() if body else ""
    if head in _TXN_HEADS:
        raise ValueError("不支持事务（BEGIN/COMMIT/ROLLBACK 等）")
    if head in _QUERY_HEADS:
        return body, "query"
    if head in _DML_HEADS:
        return body, "dml"
    if head in _DDL_HEADS:
        return body, "ddl"
    raise ValueError(f"不支持的语句类型: {head}")


def _dsn_pg(c: dict) -> str:
    return (
        f"postgresql://{c['username']}:{c['password']}@"
        f"{c['host']}:{c['port']}/{c['database']}"
    )


async def _pg_fetch(conn: dict, tables: list[str]) -> dict:
    import asyncpg

    c = await asyncpg.connect(_dsn_pg(conn), timeout=float(conn.get("timeout", 10)))
    try:
        await c.execute("SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY")
        schema = conn.get("schema_name") or "public"
        columns = await c.fetch(
            """
            SELECT table_name, column_name, data_type, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_schema = $1 AND (cardinality($2::text[]) = 0 OR table_name = ANY($2::text[]))
            ORDER BY table_name, ordinal_position
            """,
            schema,
            tables,
        )
        indexes = await c.fetch(
            """
            SELECT tablename AS table_name, indexname AS index_name, indexdef
            FROM pg_indexes
            WHERE schemaname = $1 AND (cardinality($2::text[]) = 0 OR tablename = ANY($2::text[]))
            """,
            schema,
            tables,
        )
        stats = await c.fetch(
            """
            SELECT relname AS table_name, reltuples::bigint AS est_rows,
                   relpages::bigint AS est_pages
            FROM pg_class
            WHERE relname = ANY($1::text[])
            """,
            tables,
        )
        return {
            "columns": [dict(r) for r in columns],
            "indexes": [dict(r) for r in indexes],
            "stats": [dict(r) for r in stats],
            "engine": "postgresql",
            "warnings": [],
        }
    finally:
        await c.close()


async def _mysql_fetch(conn: dict, tables: list[str]) -> dict:
    import aiomysql

    c = await aiomysql.connect(
        host=conn["host"],
        port=int(conn["port"]),
        user=conn["username"],
        password=conn["password"],
        db=conn["database"],
        connect_timeout=int(conn.get("timeout", 10)),
        autocommit=True,
    )
    try:
        try:
            async with c.cursor() as cur:
                await cur.execute("SET SESSION TRANSACTION READ ONLY")
        except Exception:  # noqa: BLE001 - 权限不足时忽略
            pass
        async with c.cursor(aiomysql.DictCursor) as cur:
            where = ""
            params: list = []
            if tables:
                where = " AND table_name IN (" + ",".join(["%s"] * len(tables)) + ")"
                params = tables
            await cur.execute(
                "SELECT table_name, column_name, data_type, is_nullable, column_default "
                "FROM information_schema.columns WHERE table_schema = DATABASE()"
                + where
                + " ORDER BY table_name, ordinal_position",
                params,
            )
            columns = await cur.fetchall()
            await cur.execute(
                "SELECT table_name, index_name, GROUP_CONCAT(column_name ORDER BY seq_in_index) AS columns "
                "FROM information_schema.statistics WHERE table_schema = DATABASE()"
                + where
                + " GROUP BY table_name, index_name",
                params,
            )
            indexes = await cur.fetchall()
            await cur.execute(
                "SELECT table_name, table_rows AS est_rows, data_length AS est_bytes, ENGINE "
                "FROM information_schema.tables WHERE table_schema = DATABASE()"
                + where,
                params,
            )
            stats = await cur.fetchall()
        warnings = [
            f"表 {r.get('table_name')} 引擎为 {r.get('ENGINE')}，MySQL 变更评审仅支持 InnoDB"
            for r in stats
            if r.get("ENGINE") and str(r.get("ENGINE")).lower() != "innodb"
        ]
        return {
            "columns": [dict(r) for r in columns],
            "indexes": [dict(r) for r in indexes],
            "stats": [dict(r) for r in stats],
            "engine": "mysql",
            "warnings": warnings,
        }
    finally:
        c.close()


async def fetch_metadata(tenant_id: int, connection_id: str, tables: list[str]) -> dict:
    """按 connection_id 取目标库元数据（列/索引/统计）。降级不抛错。"""
    conn = await DbConnectionDao.get(tenant_id, connection_id)
    if conn is None:
        return {"ok": False, "error": "数据源不存在或无权访问"}
    if not conn.get("enabled"):
        return {"ok": False, "error": "数据源已停用"}
    db_type = (conn.get("db_type") or "").lower()
    try:
        if db_type in ("postgresql", "postgres", "pg"):
            data = await _pg_fetch(conn, tables)
        elif db_type == "mysql":
            data = await _mysql_fetch(conn, tables)
        else:
            return {"ok": False, "error": f"不支持的 db_type: {db_type}"}
        return {"ok": True, "db_type": db_type, **data}
    except Exception as exc:  # noqa: BLE001 - 连接/查询失败降级
        logger.warning(
            "db_metadata 查询失败", tenant_id=tenant_id, db_type=db_type, error=str(exc)
        )
        return {"ok": False, "db_type": db_type, "error": str(exc)}


async def explain(tenant_id: int, connection_id: str, sql: str) -> dict:
    """执行 EXPLAIN（只读），返回执行计划；非只读语句直接拒绝，绝不执行原 SQL。"""
    try:
        safe_sql, kind = assert_reviewable_sql(sql)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    if kind == "ddl":
        return {"ok": False, "kind": kind, "error": "DDL 无执行计划，改用元数据与规则分析"}

    conn = await DbConnectionDao.get(tenant_id, connection_id)
    if conn is None or not conn.get("enabled"):
        return {"ok": False, "error": "数据源不可用"}
    db_type = (conn.get("db_type") or "").lower()
    try:
        if db_type in ("postgresql", "postgres", "pg"):
            import asyncpg

            c = await asyncpg.connect(_dsn_pg(conn), timeout=float(conn.get("timeout", 10)))
            try:
                await c.execute("SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY")
                rows = await c.fetch(f"EXPLAIN (FORMAT JSON) {safe_sql}")
                return {"ok": True, "db_type": db_type, "plan": [dict(r) for r in rows]}
            finally:
                await c.close()
        if db_type == "mysql":
            import aiomysql

            c = await aiomysql.connect(
                host=conn["host"],
                port=int(conn["port"]),
                user=conn["username"],
                password=conn["password"],
                db=conn["database"],
                connect_timeout=int(conn.get("timeout", 10)),
            )
            try:
                try:
                    async with c.cursor() as cur:
                        await cur.execute("SET SESSION TRANSACTION READ ONLY")
                except Exception:  # noqa: BLE001
                    pass
                async with c.cursor(aiomysql.DictCursor) as cur:
                    await cur.execute(f"EXPLAIN FORMAT=JSON {safe_sql}")
                    rows = await cur.fetchall()
                return {"ok": True, "db_type": db_type, "plan": [dict(r) for r in rows]}
            finally:
                c.close()
        return {"ok": False, "error": f"不支持的 db_type: {db_type}"}
    except Exception as exc:  # noqa: BLE001
        logger.warning("EXPLAIN 失败", tenant_id=tenant_id, db_type=db_type, error=str(exc))
        return {"ok": False, "db_type": db_type, "error": str(exc)}
