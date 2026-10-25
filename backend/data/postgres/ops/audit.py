"""审计日志。"""
from __future__ import annotations

from sqlalchemy import BigInteger, Index, String, Text, UUID, text
from sqlalchemy.orm import Mapped, mapped_column

from backend.data.postgres.base import TimestampMixin, Base


class AgentAuditLog(TimestampMixin, Base):
    """审计：业务操作留痕（谁在何时改了谁，含结果与来源）。

    登录事件不写本表，见 agent_login_log（成功与失败都要记，且 user_id 可能为空）。
    """

    __tablename__ = "agent_audit_log"
    __table_args__ = (
        # 审计按 (租户, 时间) 过滤并倒序分页；复合索引让 WHERE+ORDER BY 都走索引
        Index("ix_agent_audit_log_tenant_time", "tenant_id", "create_at"),
        {"comment": "审计日志（业务操作）"},
    )

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, server_default=text("uuid_generate_v4()"),
        comment="主键（UUID）",
    )
    tenant_id: Mapped[int] = mapped_column(BigInteger, comment="租户ID（隔离边界，BigInteger）")
    user_id: Mapped[int] = mapped_column(BigInteger, default=0, comment="操作人（user_id，BigInteger）")
    action: Mapped[str] = mapped_column(String(64), default="", comment="操作类型")
    target: Mapped[str] = mapped_column(String(128), default="", comment="操作对象")
    detail: Mapped[str] = mapped_column(Text, default="{}", comment="操作详情（JSON）")
    result: Mapped[str] = mapped_column(
        String(16), default="成功", comment="操作结果（成功/失败/待处理）"
    )
    trace_id: Mapped[str | None] = mapped_column(String(64), comment="链路追踪ID")
    ip: Mapped[str | None] = mapped_column(String(64), comment="操作来源IP")
