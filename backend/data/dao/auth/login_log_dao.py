"""登录日志 DAO：写入与查询（agent_login_log）。

写入是旁路：写失败只告警，不影响登录结果。
"""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import text

from backend.app_state import app_state
from backend.common.logger import logger
from backend.data.sql import fetch_page, session_scope

_INSERT = text("""
INSERT INTO agent_login_log (
    user_id, username, tenant_id, login_type, success, fail_reason, ip, user_agent, client, trace_id
) VALUES (
    :user_id, :username, :tenant_id, :login_type, :success, :fail_reason, :ip, :user_agent, :client, :trace_id
)
""")

# 时间倒序；tenant_id 为空表示全平台（仅超管）
_LIST = text("""
SELECT l.id, l.user_id, l.username, l.tenant_id,
       COALESCE(t.name, CASE WHEN l.tenant_id IS NULL THEN NULL
                            ELSE '租户#' || l.tenant_id::text END) AS tenant_name,
       l.login_type, l.success, l.fail_reason,
       l.ip, l.user_agent, l.client, l.trace_id, l.create_at
FROM agent_login_log l
LEFT JOIN agent_tenant t ON t.id = l.tenant_id
WHERE (CAST(:tenant_id AS BIGINT) IS NULL OR l.tenant_id = CAST(:tenant_id AS BIGINT))
ORDER BY l.create_at DESC
LIMIT :limit OFFSET :offset
""")

_COUNT = text("""
SELECT count(*) FROM agent_login_log l
WHERE (CAST(:tenant_id AS BIGINT) IS NULL OR l.tenant_id = CAST(:tenant_id AS BIGINT))
""")


class LoginLogDao:
    """登录日志读写（仅 insert + select）。"""

    @staticmethod
    async def write(
        *,
        success: bool,
        username: Optional[str] = None,
        user_id: Optional[int] = None,
        tenant_id: Optional[int] = None,
        login_type: str = "password",
        fail_reason: Optional[str] = None,
        ip: Optional[str] = None,
        user_agent: Optional[str] = None,
        client: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> None:
        """写入一条登录记录；数据库未就绪或写失败时只告警。"""
        if app_state.db_engine is None:
            return  # 单测/降级场景没有数据库，跳过
        try:
            async with session_scope() as session:
                await session.execute(
                    _INSERT,
                    {
                        "user_id": user_id,
                        "username": username,
                        "tenant_id": tenant_id,
                        "login_type": login_type,
                        "success": success,
                        "fail_reason": fail_reason,
                        "ip": ip,
                        "user_agent": user_agent,
                        "client": client,
                        "trace_id": trace_id,
                    },
                )
                await session.commit()
        except Exception:  # noqa: BLE001  登录日志是旁路，失败不影响登录
            logger.exception("登录日志落库失败（不影响登录结果）")

    @staticmethod
    async def query(
        tenant_id: Optional[int] = None, page: int = 1, page_size: int = 20
    ) -> tuple[list[dict[str, Any]], int]:
        async with session_scope() as session:
            return await fetch_page(
                session,
                _LIST,
                _COUNT,
                {"tenant_id": tenant_id},
                page=page,
                page_size=page_size,
            )
