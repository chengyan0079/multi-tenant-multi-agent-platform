"""SQL 访问层的两条底线：

1. 审计列由代码注入：请求期取上下文，非请求期必须显式传值，漏填直接报错；
2. DAO 里的 SQL 参数名必须与 schema.sql 的真实列名一致，避免改名后 SQL 静默失效。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from backend.app_state import tenant_id_ctx, user_id_ctx
from backend.data.dao.agent import agent_dao, thread_dao
from backend.data.dao.auth import login_log_dao, rbac_dao
from backend.data.dao.ops import api_log_dao, audit_dao, config_dao
from backend.data.sql.audit import (
    SYSTEM_USER_ID,
    audit_on_insert,
    audit_on_update,
)

ROOT = Path(__file__).resolve().parents[3]
SCHEMA = ROOT / "scripts" / "schema.sql"


@pytest.fixture()
def clear_identity() -> None:
    """模拟非请求期（启动期种子 / 修数脚本）：无任何身份上下文。"""
    user_id_ctx.set(None)
    tenant_id_ctx.set(None)


@pytest.fixture()
def request_identity() -> None:
    """模拟请求期：租户 200 / 用户 2001。"""
    t = tenant_id_ctx.set(200)
    u = user_id_ctx.set(2001)
    yield
    tenant_id_ctx.reset(t)
    user_id_ctx.reset(u)


def _columns_of(table: str) -> set[str]:
    """从 schema.sql 的建表语句里取列名（DDL 是表结构的唯一真相）。"""
    ddl = SCHEMA.read_text(encoding="utf-8")
    match = re.search(rf"CREATE TABLE IF NOT EXISTS {table} \((.*?)\n\);", ddl, re.S)
    assert match is not None, f"{table} 不在 schema.sql 里"
    return {
        line.strip().split()[0]
        for line in match.group(1).splitlines()
        if line.strip() and not line.strip().startswith("PRIMARY KEY")
    }


def _params_of(stmt: object) -> set[str]:
    """取 text() 语句里用到的绑定参数名。"""
    return set(re.findall(r":(\w+)", str(stmt)))


def _insert_columns(stmt: object) -> tuple[str, set[str]]:
    """取 INSERT 语句的目标表与列清单。"""
    match = re.search(r"INSERT INTO (\w+) \((.*?)\)\s*VALUES", str(stmt), re.S)
    assert match is not None, "不是合法的 INSERT 语句"
    columns = {c.strip() for c in match.group(2).replace("\n", " ").split(",") if c.strip()}
    return match.group(1), columns


# ---------------- 审计列注入 ----------------


def test_insert_fills_from_context(request_identity: None) -> None:
    """请求期：用户/租户审计列都从上下文取，创建人与更新人一致。"""
    params = audit_on_insert()

    assert params == {
        "create_user_id": 2001,
        "update_user_id": 2001,
        "create_tenant_id": 200,
        "update_tenant_id": 200,
    }


def test_insert_user_only_table_skips_tenant(request_identity: None) -> None:
    """全局表（只有用户审计列）不要求租户上下文。"""
    params = audit_on_insert(with_tenant=False)

    assert params == {"create_user_id": 2001, "update_user_id": 2001}


def test_insert_without_context_raises(clear_identity: None) -> None:
    """无上下文且没显式传值：直接报错，指出该填哪一列。"""
    with pytest.raises(RuntimeError, match="create_user_id"):
        audit_on_insert()


def test_insert_allows_null_tenant_for_super_admin() -> None:
    """超管不挂租户：上下文有用户、无租户时，租户审计列写 NULL 而不是报错。"""
    u = user_id_ctx.set(2001)
    t = tenant_id_ctx.set(None)
    try:
        params = audit_on_insert()
    finally:
        user_id_ctx.reset(u)
        tenant_id_ctx.reset(t)

    assert params["create_user_id"] == 2001
    assert params["create_tenant_id"] is None
    assert params["update_tenant_id"] is None


def test_insert_explicit_value_wins(clear_identity: None) -> None:
    """启动期写入：显式传值即可。"""
    params = audit_on_insert(user_id=SYSTEM_USER_ID, tenant_id=200)

    assert params["create_user_id"] == SYSTEM_USER_ID
    assert params["create_tenant_id"] == 200


def test_update_refreshes_operator(request_identity: None) -> None:
    """更新：update_* 跟着当前操作者走。"""
    params = audit_on_update()

    assert params == {"update_user_id": 2001, "update_tenant_id": 200}


def test_update_without_context_keeps_original(clear_identity: None) -> None:
    """后台任务更新：没有上下文就不冒充操作者，返回空参数。"""
    assert audit_on_update() == {}


# ---------------- SQL 与 DDL 对齐 ----------------


_INSERT_STATEMENTS = [
    (thread_dao._INSERT, "agent_thread"),
    (api_log_dao._INSERT, "agent_api_call_log"),
    (audit_dao._INSERT, "agent_audit_log"),
    (login_log_dao._INSERT, "agent_login_log"),
    (agent_dao._INSERT_AGENT, "agent"),
    (config_dao._INSERT_REQUEST, "agent_config_approval"),
    (config_dao._INSERT_REVIEW, "agent_config_review"),
    (rbac_dao._INSERT_ROLE, "agent_role"),
    (rbac_dao._INSERT_PERMISSION, "agent_role_permission"),
    (rbac_dao._UPSERT_MEMBERSHIP, "agent_user_tenant"),
]


@pytest.mark.parametrize(("stmt", "table"), _INSERT_STATEMENTS)
def test_insert_columns_match_table_columns(stmt: object, table: str) -> None:
    """INSERT 的列清单必须是表里真实存在的列。"""
    target, columns = _insert_columns(stmt)

    assert target == table
    unknown = columns - _columns_of(table)
    assert not unknown, f"{table} INSERT 引用了不存在的列: {unknown}"


# 允许由 SQL 函数（如 now()）直接赋值的列，其余列都必须有绑定参数
_SQL_FILLED_COLUMNS = {"create_at", "updated_at", "created_at"}


@pytest.mark.parametrize(("stmt", "_table"), _INSERT_STATEMENTS)
def test_insert_params_cover_all_columns(stmt: object, _table: str) -> None:
    """除时间列外，每个 INSERT 列都要有同名绑定参数，避免漏传变成 NULL。"""
    _, columns = _insert_columns(stmt)
    params = _params_of(stmt)

    assert params <= columns, f"参数没有对应列: {params - columns}"
    assert columns - params <= _SQL_FILLED_COLUMNS, f"列缺少绑定参数: {columns - params - _SQL_FILLED_COLUMNS}"


@pytest.mark.parametrize("column", ["create_user_id", "update_user_id"])
def test_user_audit_columns_stay_not_null_without_default(column: str) -> None:
    """操作人审计列不许加 DEFAULT：漏填必须报错，而不是静默落到 1001。"""
    ddl = SCHEMA.read_text(encoding="utf-8")

    assert re.search(rf"{column} BIGINT NOT NULL", ddl), f"{column} 应为 NOT NULL"
    assert not re.search(rf"{column} BIGINT[^,\n]*DEFAULT", ddl), f"{column} 不应有 DEFAULT"


@pytest.mark.parametrize("column", ["create_tenant_id", "update_tenant_id"])
def test_tenant_audit_columns_nullable_without_default(column: str) -> None:
    """租户审计列允许为空（超管不挂租户），但仍不许有 DEFAULT 静默兜底。"""
    ddl = SCHEMA.read_text(encoding="utf-8")

    assert not re.search(rf"{column} BIGINT NOT NULL", ddl), f"{column} 应为可空"
    assert not re.search(rf"{column} BIGINT[^,\n]*DEFAULT", ddl), f"{column} 不应有 DEFAULT"


# ---------------- 动态 WHERE 拼装 ----------------


def test_build_filters_without_conditions() -> None:
    """无条件时不生成 WHERE，参数为空。"""
    where, params = config_dao._build_filters(
        status=None, group_id=None, applicant_user_id=None
    )

    assert where == ""
    assert params == {}


def test_build_filters_combines_conditions() -> None:
    """多个条件下条件用 AND 串联，值全部走绑定参数。"""
    where, params = config_dao._build_filters(
        status=1, group_id="prompt", applicant_user_id="2001"
    )

    assert where == (
        " WHERE status = :status AND group_id = :group_id AND applicant_user_id = :applicant_user_id"
    )
    assert params == {"status": 1, "group_id": "prompt", "applicant_user_id": "2001"}
