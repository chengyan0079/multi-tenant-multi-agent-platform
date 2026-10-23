"""API 调用日志模型（agent_api_call_log）：一条请求一行，对齐 RAG-Ultra。

由 middleware.api_log.ApiLogMiddleware 写入：请求进入时采集请求侧信息，响应返回后补齐响应侧，
一次调用在表中只落一行。敏感头脱敏；req/resp body 超上限截断；multipart 不记录请求体。
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, BigInteger, DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.orm_models.base import Base


class ApiCallLog(Base):
    """API 调用日志：一次调用一行（请求侧 + 响应侧 + 耗时）。"""

    __tablename__ = "agent_api_call_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, comment="主键")
    trace_id: Mapped[str | None] = mapped_column(String(64), comment="链路追踪ID（X-Trace-Id）")
    caller: Mapped[str | None] = mapped_column(String(128), comment="调用方（X-Forwarded-For 首段 / client host）")
    user_id: Mapped[str | None] = mapped_column(String(64), comment="用户ID（X-User-Id，网关下发）")
    tenant_id: Mapped[str | None] = mapped_column(String(64), comment="租户ID（X-Tenant-Id，可为空）")
    method: Mapped[str] = mapped_column(String(16), nullable=False, comment="HTTP 方法（GET/POST/...）")
    path: Mapped[str] = mapped_column(String(512), nullable=False, comment="请求路径（不含 query）")
    route: Mapped[str | None] = mapped_column(String(512), comment="匹配路由模板（如 /admin/files/{oss_key}）")
    query_string: Mapped[str | None] = mapped_column(String(1024), comment="查询字符串")
    req_headers: Mapped[dict | None] = mapped_column(JSON, comment="请求头（JSON；敏感头已脱敏）")
    req_body: Mapped[str | None] = mapped_column(Text, comment="请求体（POST 记 JSON；multipart/超长不记录）")
    req_time: Mapped[datetime] = mapped_column(DateTime, nullable=False, comment="请求时间")
    status_code: Mapped[int | None] = mapped_column(Integer, comment="HTTP 状态码")
    resp_body: Mapped[str | None] = mapped_column(Text, comment="响应体（JSON；超长截断）")
    resp_time: Mapped[datetime | None] = mapped_column(DateTime, comment="响应时间")
    cost_ms: Mapped[int] = mapped_column(Integer, default=0, comment="耗时（毫秒）")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, comment="创建时间")

    __table_args__ = (
        Index("idx_trace", "trace_id"),
        Index("idx_path_time", "path", "req_time"),
        Index("idx_req_time", "req_time"),
    )
