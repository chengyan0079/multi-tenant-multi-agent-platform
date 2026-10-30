"""配置中心审批流 DAO：`agent_config_approval` / `agent_config_review`。

系统级表（无 tenant_id、无审计列），只有 create_at / updated_at。
与其他 DAO 的区别：方法接收调用方传入的 session，**事务边界由 service 控制**
（申请 → 复核 → 执行是一个跨 Nacos 调用的长事务，不能在 DAO 里 commit）。
"""
from __future__ import annotations

from typing import Any, Iterable

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.data.sql import execute_write, fetch_all, fetch_one, fetch_value

# 写入列白名单：调用方传什么就写什么，多余字段直接丢弃（防止拼错列名静默变成绑定失败）
_INSERT_COLUMNS = (
    "namespace",
    "group_id",
    "data_id",
    "op_type",
    "title",
    "content_new",
    "content_format",
    "reason",
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
    "effective_at",
)

_INSERT_REQUEST = text(f"""
INSERT INTO agent_config_approval (
    {", ".join(_INSERT_COLUMNS)}
) VALUES (
    {", ".join(":" + c for c in _INSERT_COLUMNS)}
)
RETURNING *
""")

_SELECT_REQUEST = text("""
SELECT *
FROM agent_config_approval
WHERE id = :request_id
""")

_INSERT_REVIEW = text("""
INSERT INTO agent_config_review (approval_id, reviewer_user_id, action, comment)
VALUES (:approval_id, :reviewer_user_id, :action, :comment)
""")

_COUNT_REQUESTS = "SELECT count(*) FROM agent_config_approval"
_COUNT_REVIEWS = "SELECT count(*) FROM agent_config_review"


def _build_filters(
    *, status: int | None, group_id: str | None, applicant_user_id: str | None
) -> tuple[str, dict[str, Any]]:
    """拼 WHERE 子句：列名写死、值走绑定参数，避免拼接注入。"""
    conditions: list[str] = []
    params: dict[str, Any] = {}
    if status is not None:
        conditions.append("status = :status")
        params["status"] = status
    if group_id:
        conditions.append("group_id = :group_id")
        params["group_id"] = group_id
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
        approval_id: int,
        reviewer_user_id: int | None,
        action: int,
        comment: str | None,
    ) -> None:
        """登记复核记录（不提交）。"""
        await execute_write(
            session,
            _INSERT_REVIEW,
            {
                "approval_id": approval_id,
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
        """按白名单更新申请状态字段，返回受影响行数。

        `effective_at=True` 是哨兵值：表示用库端 now() 写入生效时间
        （只在状态进入终态 2 驳回 / 3 已执行 / 4 撤回 时使用），避免应用与库时区不一致。
        """
        updates = {k: v for k, v in fields.items() if k in _UPDATE_COLUMNS}
        if not updates:
            return 0
        assignments: list[str] = []
        params: dict[str, Any] = {"request_id": request_id}
        for key, value in updates.items():
            if key == "effective_at" and value is True:
                assignments.append("effective_at = now()")
                continue
            assignments.append(f"{key} = :{key}")
            params[key] = value
        stmt = text(
            f"UPDATE agent_config_approval SET {', '.join(assignments)} WHERE id = :request_id"
        )
        return await execute_write(session, stmt, params)

    @staticmethod
    async def list_requests(
        session: AsyncSession,
        *,
        status: int | None = None,
        group_id: str | None = None,
        applicant_user_id: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        """审批单列表（条件筛选 + 分页），返回 (行, 总数)。"""
        where, params = _build_filters(
            status=status, group_id=group_id, applicant_user_id=applicant_user_id
        )
        total = await fetch_value(session, text(_COUNT_REQUESTS + where), params) or 0
        rows = await fetch_all(
            session,
            text(
                f"SELECT * FROM agent_config_approval{where}"
                " ORDER BY create_at DESC LIMIT :limit OFFSET :offset"
            ),
            {**params, "limit": page_size, "offset": (page - 1) * page_size},
        )
        return rows, int(total)

    @staticmethod
    async def list_reviews(
        session: AsyncSession, *, approval_id: int
    ) -> list[dict[str, Any]]:
        """某审批单的全部复核记录（按时间正序，用于审核历史查看）。"""
        return await fetch_all(
            session,
            text(
                "SELECT * FROM agent_config_review "
                "WHERE approval_id = :approval_id ORDER BY create_at ASC"
            ),
            {"approval_id": approval_id},
        )

    @staticmethod
    async def resolve_usernames(
        session: AsyncSession, user_ids: Iterable[int | None]
    ) -> dict[int, str]:
        """把一批 user_id 批量解析为 username，供审批单展示申请人/复核人而非裸 id。"""
        ids = sorted({int(uid) for uid in user_ids if uid is not None})
        if not ids:
            return {}
        placeholders = ", ".join(f":uid{i}" for i in range(len(ids)))
        params = {f"uid{i}": uid for i, uid in enumerate(ids)}
        rows = await fetch_all(
            session,
            text(f"SELECT id, username FROM agent_user WHERE id IN ({placeholders})"),
            params,
        )
        return {int(r["id"]): r["username"] for r in rows if r.get("username")}

    @staticmethod
    async def list_all_reviews(
        session: AsyncSession, *, page: int = 1, page_size: int = 20
    ) -> tuple[list[dict[str, Any]], int]:
        """全量复核记录（审核日志页）：关联复核人用户名与所属审批单信息。"""
        total = await fetch_value(session, text(_COUNT_REVIEWS)) or 0
        rows = await fetch_all(
            session,
            text(
                """
                SELECT rv.id, rv.approval_id, rv.reviewer_user_id, rv.action,
                       rv.comment, rv.create_at,
                       u.username AS reviewer_name,
                       ap.data_id, ap.group_id, ap.namespace, ap.op_type,
                       ap.title, ap.status AS approval_status
                FROM agent_config_review rv
                LEFT JOIN agent_user u ON u.id = rv.reviewer_user_id
                LEFT JOIN agent_config_approval ap ON ap.id = rv.approval_id
                ORDER BY rv.create_at DESC, rv.id DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            {"limit": page_size, "offset": (page - 1) * page_size},
        )
        return rows, int(total)
