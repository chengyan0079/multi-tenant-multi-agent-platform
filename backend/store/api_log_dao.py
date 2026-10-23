"""API 调用日志 DAO：把一次调用的"请求 + 响应"落一行（agent_api_call_log）。

落库是旁路：写失败仅告警，绝不影响接口返回。
"""
from __future__ import annotations

from typing import Any

from backend.app_state import app_state
from backend.common.logger import logger
from backend.orm_models.api_log import ApiCallLog


class ApiLogDao:
    """API 调用日志落库（一条请求一行）。"""

    async def save(self, record: dict[str, Any]) -> None:
        """写入一行；引擎未就绪或写库异常时仅告警。"""
        if app_state.db_engine is None:
            return  # 数据库未启动（如单测/降级），跳过落库
        try:
            from backend.orm_models import session_scope

            async with session_scope() as session:
                session.add(ApiCallLog(**record))
                await session.commit()
        except Exception:  # noqa: BLE001  日志旁路：失败不影响主链路
            logger.exception("API 调用日志落库失败（不影响接口返回）")
