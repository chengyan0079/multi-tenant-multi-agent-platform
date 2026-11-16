"""SQL 脚本上传/校验：固定 .sql 后缀 + 按 db_type 校验。

合法性（语法/方言/事务/单语句）用 sqlglot 解析器判定，**不调用 LLM**（快、无幻觉）。
- 固定 .sql 后缀；
- 方言关键字提示（轻量）；
- 语法解析、单语句、禁事务；DDL/DML 均支持（只分析不执行）。
"""

from __future__ import annotations

import sqlglot
from sqlglot import exp

# 各方言专有关键字（出现即提示方言可能不匹配）
_DIALECT_MARKERS: dict[str, set[str]] = {
    "mysql": {
        "AUTO_INCREMENT",
        "ENGINE=",
        "UNSIGNED",
        "CHARSET",
        "ROW_FORMAT",
        "KEY_BLOCK_SIZE",
    },
    "postgresql": {
        "SERIAL",
        "BIGSERIAL",
        "JSONB",
        "ILIKE",
        "RETURNING",
        "ON CONFLICT",
        "VACUUM",
        "TABLESPACE",
    },
}
_FOREIGN = {"mysql": "postgresql", "postgresql": "mysql"}
_ALIASES = {"postgres": "postgresql", "pg": "postgresql", "mysql": "mysql"}
_SQLGLOT_DIALECT = {"mysql": "mysql", "postgresql": "postgres"}

DEFAULT_MAX_BYTES = 16 * 1024

_TXN_TYPE_NAMES = {"Transaction", "Commit", "Rollback", "Begin", "Start"}


def normalize_db_type(db_type: str) -> str:
    """归一化目标库类型（postgres/pg → postgresql）。"""
    return _ALIASES.get((db_type or "").strip().lower(), (db_type or "").strip().lower())


def ensure_sql_filename(name: str) -> str:
    """脚本存储名固定 .sql：取 basename、去原扩展名、补 .sql。"""
    base = (name or "script").strip().replace("\\", "/").rsplit("/", 1)[-1]
    if "." in base:
        base = base.rsplit(".", 1)[0]
    return f"{base or 'script'}.sql"


def parse_sql(sql: str, db_type: str) -> dict:
    """用 sqlglot 按方言解析 SQL，判定合法性（不调 LLM）。

    返回 {ok, errors, warnings, kinds}：
    - 语法错误/多语句/事务 → ok=False；
    - 方言关键字不符 → warnings；
    - kinds 为各语句类型名（Select/Update/Alter...）。
    """
    errors: list[str] = []
    warnings: list[str] = []
    kinds: list[str] = []

    text = (sql or "").strip()
    if not text:
        return {"ok": False, "errors": ["SQL 为空"], "warnings": [], "kinds": []}

    dialect = _SQLGLOT_DIALECT.get(normalize_db_type(db_type))
    if dialect is None:
        return {
            "ok": False,
            "errors": [f"不支持的 db_type: {db_type}"],
            "warnings": [],
            "kinds": [],
        }

    try:
        stmts = [s for s in sqlglot.parse(text, read=dialect) if s is not None]
    except Exception as exc:  # noqa: BLE001 - 解析失败即语法非法
        return {
            "ok": False,
            "errors": [f"SQL 语法解析失败: {exc}"],
            "warnings": [],
            "kinds": [],
        }

    if not stmts:
        return {"ok": False, "errors": ["SQL 解析为空"], "warnings": [], "kinds": []}
    if len(stmts) > 1:
        errors.append("仅支持单条语句（禁止多语句）")

    for s in stmts:
        name = type(s).__name__
        kinds.append(name)
        if name in _TXN_TYPE_NAMES:
            errors.append("不支持事务（BEGIN/COMMIT/ROLLBACK 等）")

    dt = normalize_db_type(db_type)
    foreign = _FOREIGN.get(dt)
    if foreign:
        upper = text.upper()
        for kw in _DIALECT_MARKERS.get(foreign, set()):
            if kw.upper() in upper:
                warnings.append(f"检测到 {foreign} 专有关键字 '{kw}'，与目标库 {dt} 不符")

    return {"ok": not errors, "errors": errors, "warnings": warnings, "kinds": kinds}


_CONST_TRUE_OR = (exp.Or,)


def _const_true(expr) -> bool:
    """判断条件表达式是否恒真（AST 级，方言无关）。"""
    if expr is None:
        return False
    if isinstance(expr, exp.Boolean) and expr.this is True:
        return True
    if isinstance(expr, exp.EQ):
        left, right = expr.left, expr.right
        if isinstance(left, exp.Literal) and isinstance(right, exp.Literal):
            if left.this == right.this:
                return True
        if (
            isinstance(left, exp.Column)
            and isinstance(right, exp.Column)
            and left.name.lower() == right.name.lower()
        ):
            return True
    if isinstance(expr, exp.Paren):
        return _const_true(expr.this)
    if isinstance(expr, exp.Or):
        return _const_true(expr.left) or _const_true(expr.right)
    return False


def analyze_sql(sql: str, db_type: str) -> dict:
    """用 sqlglot AST 分析语句（方言无关，不调 LLM）。

    返回 {ok, kind, kinds, has_where, where_always_true, errors}：
    - kind: query / dml / ddl / txn / other；
    - 依赖 sqlglot 按方言解析，不硬编码关键字，适配 MySQL/PG 等多方言。
    """
    dialect = _SQLGLOT_DIALECT.get(normalize_db_type(db_type))
    if dialect is None:
        return {"ok": False, "errors": [f"不支持的 db_type: {db_type}"]}
    try:
        stmts = [s for s in sqlglot.parse(sql or "", read=dialect) if s is not None]
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "errors": [f"SQL 语法解析失败: {exc}"]}
    if not stmts:
        return {"ok": False, "errors": ["SQL 解析为空"]}
    first = stmts[0]
    kinds = [type(s).__name__ for s in stmts]

    if isinstance(first, (exp.Create, exp.Alter, exp.Drop, exp.TruncateTable)):
        kind = "ddl"
    elif isinstance(first, (exp.Insert, exp.Update, exp.Delete, exp.Merge)):
        kind = "dml"
    elif isinstance(first, (exp.Select, exp.Union, exp.Subquery)):
        kind = "query"
    elif type(first).__name__ in _TXN_TYPE_NAMES:
        kind = "txn"
    else:
        kind = "other"

    where = first.find(exp.Where)
    return {
        "ok": True,
        "kind": kind,
        "kinds": kinds,
        "has_where": where is not None,
        "where_always_true": _const_true(where.this) if where is not None else False,
    }


def validate_script(
    text: str, db_type: str, *, max_bytes: int = DEFAULT_MAX_BYTES
) -> dict:
    """校验脚本：非空 / 长度 / 语法合法性（sqlglot）/ 方言关键字。

    返回 {ok, errors, warnings}；不调用 LLM。
    """
    errors: list[str] = []
    warnings: list[str] = []

    if not text or not text.strip():
        return {"ok": False, "errors": ["脚本内容为空"], "warnings": []}
    if len(text.encode("utf-8")) > max_bytes:
        errors.append(f"脚本超过 {max_bytes} 字节，请上传 .sql 文件")

    parsed = parse_sql(text, db_type)
    errors.extend(parsed.get("errors") or [])
    warnings.extend(parsed.get("warnings") or [])

    return {"ok": not errors, "errors": errors, "warnings": warnings}
