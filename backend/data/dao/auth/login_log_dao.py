"""登录日志 DAO：写入与查询（agent_login_log）。

写入是旁路：登录成功与否不受落库结果影响，写失败只告警。
"""
from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import text

from backend.app_state import app_state
from backend.common.logger import logger

_INSERT = text("""
INSERT INTO agent_login_log (
    user_id, username, tenant_id, login_type, success, fail_reason, ip, user_agent, client, trace_id
) VALUES (
    :user_id, :username, :tenant_id, :login_type, :success, :fail_reason, :ip, :user_agent, :client, :trace_id
)
""")

# 时间倒序；tenant_id 为空表示全平台（仅超管）
_LIST = text("""
SELECT id, user_id, username, tenant_id, login_type, success, fail_reason,
       ip, user_agent, client, trace_id, create_at
FROM agent_login_log
WHERE (CAST(:tenant_id AS BIGINT) IS NULL OR tenant_id = CAST(:tenant_id AS BIGINT))
ORDER BY create_at DESC
LIMIT :limit
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
            from backend.data.sql import session_scope

            async with session_scope() as session:
                await session.execute(_INSERT, {
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
                })
                await session.commit()
        except Exception:  # noqa: BLE001  登录日志是旁路，失败不影响登录
            logger.exception("登录日志落库失败（不影响登录结果）")

    @staticmethod
    async def query(
        tenant_id: Optional[int] = None, limit: int = 200
    ) -> list[dict[str, Any]]:
        """按租户过滤查询（tenant_id=None 查全量，仅超管），时间倒序。"""
        from backend.data.sql import fetch_all, session_scope

        async with session_scope() as session:
            return await fetch_all(
                session, _LIST, {"tenant_id": tenant_id, "limit": limit}
            )
