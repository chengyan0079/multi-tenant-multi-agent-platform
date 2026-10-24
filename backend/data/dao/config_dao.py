"""配置中心审批流 DAO：`agent_config_change_request` / `agent_config_review`。

系统级表（无 tenant_id、无审计列），只有 create_at / updated_at。
与其他 DAO 的区别：方法接收调用方传入的 session，**事务边界由 service 控制**
（申请 → 复核 → 执行是一个跨 Nacos 调用的长事务，不能在 DAO 里 commit）。
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.data.sql import execute_write, fetch_all, fetch_one, fetch_value

# 写入列白名单：调用方传什么就写什么，多余字段直接丢弃（防止拼错列名静默变成绑定失败）
_INSERT_COLUMNS = (
    "namespace",
    "group_id",
    "data_id",
    "domain",
    "op_type",
    "title",
    "content_new",
    "content_format",
    "reason",
    "old_config_id",
    "old_config_md5",
    "src_history_nid",
    "status",
    "applicant_user_id",
    "reviewer_user_id",
)

# 可更新列白名单：状态机只允许改这些，id / 申请人 / 拟下发内容不在其中
_UPDATE_COLUMNS = (
    "status",
    "reviewer_user_id",
    "nacos_history_nid",
    "old_history_nid",
)

_INSERT_REQUEST = text(f"""
INSERT INTO agent_config_change_request (
    {", ".join(_INSERT_COLUMNS)}
) VALUES (
    {", ".join(":" + c for c in _INSERT_COLUMNS)}
)
RETURNING *
""")

_SELECT_REQUEST = text("""
SELECT *
FROM agent_config_change_request
WHERE id = :request_id
""")

_INSERT_REVIEW = text("""
INSERT INTO agent_config_review (request_id, reviewer_user_id, action, comment)
VALUES (:request_id, :reviewer_user_id, :action, :comment)
""")

_COUNT_REQUESTS = "SELECT count(*) FROM agent_config_change_request"


def _build_filters(
    *, status: int | None, domain: str | None, applicant_user_id: str | None
) -> tuple[str, dict[str, Any]]:
    """拼 WHERE 子句：列名写死、值走绑定参数，避免拼接注入。"""
    conditions: list[str] = []
    params: dict[str, Any] = {}
    if status is not None:
        conditions.append("status = :status")
        params["status"] = status
    if domain:
        conditions.append("domain = :domain")
        params["domain"] = domain
    if applicant_user_id:
        conditions.append("applicant_user_id = :applicant_user_id")
        params["applicant_user_id"] = applicant_user_id
    where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
    return where, params


class ConfigDao:
    """配置变更申请与复核记录的读写。"""

    @staticmethod
    async def add_request(session: AsyncSession, **fields: Any) -> dict[str, Any]:
        """新增申请，返回整行（含库端生成的 id / create_at）。"""
        params = {c: fields.get(c) for c in _INSERT_COLUMNS}
        stmt = _INSERT_REQUEST
        result = await session.execute(stmt, params)
        row = result.mappings().first()
        if row is None:  # RETURNING * 才会走到这里，正常不会发生
            raise RuntimeError("配置变更申请写入失败：未返回插入行")
        return dict(row)

    @staticmethod
    async def add_review(
        session: AsyncSession,
        *,
        request_id: int,
        reviewer_user_id: int | None,
        action: int,
        comment: str | None,
    ) -> None:
        """登记复核记录（不提交）。"""
        await execute_write(
            session,
            _INSERT_REVIEW,
            {
                "request_id": request_id,
                "reviewer_user_id": reviewer_user_id,
                "action": action,
                "comment": comment,
            },
        )

    @staticmethod
    async def get_request(
        session: AsyncSession, request_id: int, *, for_update: bool = False
    ) -> dict[str, Any] | None:
        """按 id 查申请；for_update=True 加行级锁（复核/执行必须用）。"""
        stmt = _SELECT_REQUEST
        if for_update:
            stmt = text(f"{_SELECT_REQUEST.text} FOR UPDATE")
        return await fetch_one(session, stmt, {"request_id": request_id})

    @staticmethod
    async def update_request(session: AsyncSession, request_id: int, **fields: Any) -> int:
        """按白名单更新申请状态字段，返回受影响行数。"""
        updates = {k: v for k, v in fields.items() if k in _UPDATE_COLUMNS}
        if not updates:
            return 0
        assignments = ", ".join(f"{k} = :{k}" for k in updates)
        stmt = text(
            f"UPDATE agent_config_change_request SET {assignments} WHERE id = :request_id"
        )
        return await execute_write(session, stmt, {**updates, "request_id": request_id})

    @staticmethod
    async def list_requests(
        session: AsyncSession,
        *,
        status: int | None = None,
        domain: str | None = None,
        applicant_user_id: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        """申请列表（条件筛选 + 分页），返回 (行, 总数)。"""
        where, params = _build_filters(
            status=status, domain=domain, applicant_user_id=applicant_user_id
        )
        total = await fetch_value(session, text(_COUNT_REQUESTS + where), params) or 0
        rows = await fetch_all(
            session,
            text(
                f"SELECT * FROM agent_config_change_request{where}"
                " ORDER BY create_at DESC LIMIT :limit OFFSET :offset"
            ),
            {**params, "limit": page_size, "offset": (page - 1) * page_size},
        )
        return rows, int(total)
