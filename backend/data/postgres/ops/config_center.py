"""配置中心审批流模型（系统级，无 tenant_id；历史/当前态复用 Nacos）。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, SmallInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.data.postgres.base import Base, TimestampMixin


class ConfigApproval(TimestampMixin, Base):
    """配置变更审批单（审批流，无 tenant_id；配置当前/历史态直接读 Nacos）。"""

    __tablename__ = "agent_config_approval"
    __table_args__ = (
        Index("idx_agent_config_approval_status", "status"),
        Index("idx_agent_config_approval_group", "group_id"),
        Index("idx_agent_config_approval_data", "namespace", "group_id", "data_id"),
        Index("idx_agent_config_approval_create_at", "create_at"),
        {"comment": "配置变更审批单（审批流，无tenant_id）"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, comment="主键")
    namespace: Mapped[str] = mapped_column(
        String(128), nullable=False, default="agent-platform", comment="Nacos命名空间"
    )
    group_id: Mapped[str] = mapped_column(
        String(128), nullable=False, default="DEFAULT_GROUP", comment="Nacos分组"
    )
    data_id: Mapped[str] = mapped_column(String(256), nullable=False, comment="Nacos配置ID")
    op_type: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, comment="操作类型（1新增2修改3删除4回滚）"
    )
    title: Mapped[str | None] = mapped_column(String(256), comment="标题")
    content_new: Mapped[str | None] = mapped_column(
        Text, comment="拟下发内容（全文，审批前未进Nacos；删除为NULL）"
    )
    content_format: Mapped[str] = mapped_column(
        String(16), nullable=False, default="json", comment="内容格式（json/text/yaml）"
    )
    src_history_nid: Mapped[int | None] = mapped_column(BigInteger, comment="回滚来源历史nid")
    status: Mapped[int] = mapped_column(
        SmallInteger,
        nullable=False,
        default=0,
        comment="状态（0待复核1通过待执行2驳回3已执行4撤回）",
    )
    applicant_user_id: Mapped[int | None] = mapped_column(
        BigInteger, comment="申请人user_id（BigInteger）"
    )
    reviewer_user_id: Mapped[int | None] = mapped_column(
        BigInteger, comment="复核人user_id（BigInteger）"
    )
    reason: Mapped[str | None] = mapped_column(String(512), comment="变更原因")
    nacos_history_nid: Mapped[int | None] = mapped_column(
        BigInteger, comment="执行后回填：新内容历史nid（追踪/CAS）"
    )
    effective_at: Mapped[datetime | None] = mapped_column(
        DateTime, comment="生效时间（status 变为 2/3/4 时写入，其余为空）"
    )


class ConfigReview(TimestampMixin, Base):
    """配置复核记录（审批流，无 tenant_id）。"""

    __tablename__ = "agent_config_review"
    __table_args__ = (
        Index("idx_approval", "approval_id"),
        {"comment": "配置复核记录（审批流，无tenant_id）"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, comment="主键")
    approval_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="关联审批单ID")
    reviewer_user_id: Mapped[int | None] = mapped_column(
        BigInteger, comment="复核人user_id（BigInteger）"
    )
    action: Mapped[int] = mapped_column(SmallInteger, nullable=False, comment="动作（1通过2驳回）")
    comment: Mapped[str | None] = mapped_column(String(512), comment="复核意见")
