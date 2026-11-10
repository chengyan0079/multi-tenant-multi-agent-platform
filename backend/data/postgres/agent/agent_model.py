"""agent_model 关联表：Agent 与模型多对多绑定（全局表，无 tenant 列），is_default/priority 控制默认与优先级。"""

from typing import Optional

from sqlalchemy import BigInteger, Boolean, Integer, text
from sqlalchemy.orm import Mapped, mapped_column

from backend.data.postgres.base import AuditUserOnlyMixin, Base


class AgentModelRel(AuditUserOnlyMixin, Base):
    """Agent ↔ 模型 绑定关系（agent 级模型覆盖）。"""

    __tablename__ = "agent_model"
    __table_args__ = {"comment": "Agent 与模型的多对多绑定（agent 级模型覆盖，全局表）"}

    agent_id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, comment="逻辑外键 → agent.id"
    )
    model_id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, comment="逻辑外键 → model_registry.id"
    )
    is_default: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
        comment="同类模型中的默认项（覆盖全局默认时优先取此项）",
    )
    priority: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("0"),
        comment="同类多模型的优先顺序，越小越优先",
    )
