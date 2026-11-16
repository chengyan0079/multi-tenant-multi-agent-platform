"""Agent 目录（租户级）：显式元数据入库，build_graph 仍代码注册，无物理外键。"""

from typing import Optional

from sqlalchemy import BigInteger, Boolean, JSON, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from backend.data.postgres.base import AuditUserOnlyMixin, Base


class AgentModel(AuditUserOnlyMixin, Base):
    """租户级 Agent 注册（tenant_id + agent_type 唯一，enabled 由租户控制）。"""

    __tablename__ = "agent"
    __table_args__ = (
        UniqueConstraint("tenant_id", "agent_type", name="uq_agent_tenant_type"),
        {"comment": "Agent 元数据目录（租户级）"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, comment="主键（代理键）")
    tenant_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, index=True, comment="所属租户ID"
    )
    agent_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="Agent 类型（业务键，与 AgentRegistry.agent_type 一致）",
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False, comment="Agent 展示名")
    description: Mapped[str] = mapped_column(Text, default="", comment="Agent 说明")
    input_schema: Mapped[Optional[dict]] = mapped_column(
        JSON, nullable=True, comment="输入 JSON Schema（供校验与文档）"
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("true"),
        comment="租户内是否启用（租户可控制）",
    )
    version: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'1.0.0'"), comment="版本号"
    )
