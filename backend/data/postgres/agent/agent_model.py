"""agent_model 关联表：Agent 与模型的多对多绑定（agent 级模型覆盖，全局表）。

设计说明：
- agent 与 model_registry 均为全局资源，故本表无 tenant 列（AuditUserOnlyMixin）；
- 复合主键 (agent_id, model_id)，均为逻辑外键（全库不建物理 FK）；
- 一个 agent 可绑定多个模型，同类（llm/embedding/...）可挂多个；
  `is_default` 标记同类默认项，`priority` 控制同类内的优先顺序；
- 运行时（后续接口/链路）按 (agent_id, model_type) 取该 agent 绑定的模型，
  覆盖 model_registry 的全局 active 默认。
"""
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
        Boolean, nullable=False, server_default=text("false"),
        comment="同类模型中的默认项（覆盖全局默认时优先取此项）",
    )
    priority: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0"),
        comment="同类多模型的优先顺序，越小越优先",
    )
