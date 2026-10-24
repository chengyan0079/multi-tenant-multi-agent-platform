"""Agent 元数据目录 + 租户级能力策略表（设计文档 §9.1 ④ / §15）。

设计说明：
- `agent`：全局 Agent 目录（与租户无关，故用 AuditUserOnlyMixin，无 tenant 审计列）。
  图构造器 `build_graph` 是函数、无法序列化入库，仍由代码注册到 AgentRegistry；
  本表只承载「可持久化、可展示」的元数据（展示名/描述/输入 schema/全局开关/版本）。
- `agent_capability_policy`：租户级 Agent 开通策略（Capability Gating）。
  某租户能否使用某 Agent = 全局开关 AND 本表租户策略（未配置视为开通）。
- 两表之间、以及与其余表之间均无物理外键（遵循全库「逻辑外键」策略）。
"""
from typing import Optional

from sqlalchemy import BigInteger, Boolean, JSON, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from backend.data.postgres.base import AuditMixin, AuditUserOnlyMixin, Base


class AgentModel(AuditUserOnlyMixin, Base):
    """全局 Agent 目录（agent_type 为业务键，与 AgentRegistry 注册的 agent_type 一致）。"""

    __tablename__ = "agent"
    __table_args__ = {"comment": "Agent 元数据目录（全局）"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, comment="主键（代理键）")
    agent_type: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True,
        comment="Agent 类型（业务键，与 AgentRegistry.agent_type 一致）",
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False, comment="Agent 展示名")
    description: Mapped[str] = mapped_column(Text, default="", comment="Agent 说明")
    input_schema: Mapped[Optional[dict]] = mapped_column(
        JSON, nullable=True, comment="输入 JSON Schema（供校验与文档）"
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true"),
        comment="全局启用开关（租户级开通见 agent_capability_policy）",
    )
    version: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'1.0.0'"), comment="版本号"
    )


class AgentCapabilityPolicy(AuditMixin, Base):
    """租户级 Agent 开通策略（tenant_id + agent_type 唯一）。"""

    __tablename__ = "agent_capability_policy"
    __table_args__ = (
        UniqueConstraint("tenant_id", "agent_type", name="uq_capability_tenant_agent"),
        {"comment": "租户级 Agent 开通策略"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, comment="主键（代理键）")
    tenant_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, index=True, comment="租户ID（隔离边界）"
    )
    agent_type: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True,
        comment="Agent 类型（逻辑外键→agent.agent_type，代码控制）",
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true"), comment="该租户是否开通此 Agent"
    )
