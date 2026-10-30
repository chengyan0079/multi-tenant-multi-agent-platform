"""API 调用日志模型（agent_api_call_log）：一条请求一行。

由 middleware.api_log.ApiLogMiddleware 写入：请求进入时采集请求侧信息，响应返回后补齐响应侧，
一次调用在表中只落一行。只记元数据，不存请求体/响应体（需要时用 API_LOG_SAVE_BODY 开）。
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, JSON, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from backend.data.postgres.base import Base, TimestampMixin


class ApiCallLog(TimestampMixin, Base):
    """API 调用日志：一次调用一行（请求侧 + 响应侧 + 耗时）。"""

    __tablename__ = "agent_api_call_log"
    __table_args__ = (
        Index("idx_trace", "trace_id"),
        Index("idx_path_time", "path", "req_time"),
        # 租户管理员视角按 (租户, 时间) 查本租户调用；超管视角 tenant_id 为空走 idx_req_time
        Index("ix_agent_api_call_log_tenant_time", "tenant_id", "req_time"),
        Index("idx_req_time", "req_time"),
        {"comment": "API调用日志（一次调用一行）"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, comment="主键")
    trace_id: Mapped[str | None] = mapped_column(String(64), comment="链路追踪ID（X-Trace-Id）")
    caller: Mapped[str | None] = mapped_column(String(128), comment="调用方（X-Forwarded-For首段/client host）")
    user_id: Mapped[int | None] = mapped_column(BigInteger, comment="用户ID（取自 JWT 的 user_id，BigInteger）")
    tenant_id: Mapped[int | None] = mapped_column(BigInteger, comment="租户ID（取自 JWT 的 tenant_id，可为空，BigInteger）")
    method: Mapped[str] = mapped_column(String(16), nullable=False, comment="HTTP方法（GET/POST/...）")
    path: Mapped[str] = mapped_column(String(512), nullable=False, comment="请求路径（不含query）")
    route: Mapped[str | None] = mapped_column(String(512), comment="匹配路由模板（如/admin/files/{oss_key}）")
    query_string: Mapped[str | None] = mapped_column(String(1024), comment="查询字符串")
    req_headers: Mapped[dict | None] = mapped_column(JSON, comment="请求头（JSON；敏感头已脱敏）")
    req_time: Mapped[datetime] = mapped_column(DateTime, nullable=False, comment="请求时间")
    status_code: Mapped[int | None] = mapped_column(Integer, comment="HTTP状态码")
    resp_time: Mapped[datetime | None] = mapped_column(DateTime, comment="响应时间")
    cost_ms: Mapped[int] = mapped_column(Integer, default=0, comment="耗时（毫秒）")
