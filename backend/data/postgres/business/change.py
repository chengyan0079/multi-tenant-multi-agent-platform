"""数据库变更评审（db_review）业务表：变更单 + 评审结果。"""

from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.data.postgres.base import AuditMixin, Base


class AgentChangeRequest(AuditMixin, Base):
    """数据库变更单（一次评审的主记录）。"""

    __tablename__ = "agent_change_request"
    __table_args__ = ({"comment": "数据库变更单（db_review）"},)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, comment="主键")
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True, comment="租户ID")
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="提交人")
    thread_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True, comment="会话线程")
    turn_id: Mapped[str] = mapped_column(String(64), default="", comment="本轮ID")
    title: Mapped[str] = mapped_column(String(200), default="", comment="标题")
    target_database: Mapped[str] = mapped_column(String(128), nullable=False, comment="目标库")
    db_type: Mapped[str] = mapped_column(String(16), nullable=False, comment="mysql/postgresql")
    connection_id: Mapped[str] = mapped_column(String(64), nullable=False, comment="数据源ID（图内唯一）")
    sql_text: Mapped[str] = mapped_column(Text, nullable=False, comment="SQL 脚本")
    script_file_id: Mapped[int | None] = mapped_column(BigInteger, comment="脚本文件ID（agent_file）")
    drill_file_id: Mapped[int | None] = mapped_column(BigInteger, comment="回滚演练记录PDF文件ID")
    risk_level: Mapped[str | None] = mapped_column(String(16), comment="low/medium/high/critical")
    status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default="draft",
        comment="draft/reviewing/pending_approval/approved/rejected",
    )
    trace_id: Mapped[str | None] = mapped_column(String(64), comment="trace")


class AgentChangeReview(AuditMixin, Base):
    """变更评审结果（维度表 + 优化建议）。"""

    __tablename__ = "agent_change_review"
    __table_args__ = ({"comment": "数据库变更评审结果（db_review）"},)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, comment="主键")
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True, comment="租户ID")
    request_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, index=True, comment="变更单ID"
    )
    risk_level: Mapped[str | None] = mapped_column(String(16), comment="风险等级")
    online_ddl: Mapped[bool | None] = mapped_column(Boolean, comment="是否 Online DDL")
    estimated_rows: Mapped[int | None] = mapped_column(BigInteger, comment="影响/扫描行数估算")
    lock_estimate_ms: Mapped[int | None] = mapped_column(Integer, comment="预估锁时长(ms)")
    core_path: Mapped[bool | None] = mapped_column(Boolean, comment="是否核心链路")
    cross_db: Mapped[bool | None] = mapped_column(Boolean, comment="是否跨库事务")
    rollback_ready: Mapped[bool | None] = mapped_column(Boolean, comment="回滚预案是否完整")
    slow_sql: Mapped[dict | None] = mapped_column(JSON, comment="慢SQL分析结果")
    suggestions: Mapped[list | None] = mapped_column(JSON, comment="优化建议")
    metadata_snapshot: Mapped[dict | None] = mapped_column(JSON, comment="元数据快照（DDL/索引/统计）")
    detail: Mapped[dict | None] = mapped_column(JSON, comment="完整评审明细")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="done", comment="done")


class AgentChangeRelease(AuditMixin, Base):
    """变更发布：db_release 在沙箱执行验证（即用即弃），输出原样 SQL 供人工上生产。"""

    __tablename__ = "agent_change_release"
    __table_args__ = ({"comment": "变更发布（db_release 沙箱验证）"},)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, comment="主键")
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True, comment="租户ID")
    request_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True, comment="变更单ID")
    sandbox_connection_id: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="影子库连接ID"
    )
    thread_id: Mapped[str | None] = mapped_column(
        String(128), comment="图 thread_id（HITL 恢复用）"
    )
    exec_ok: Mapped[bool | None] = mapped_column(Boolean, comment="沙箱执行是否成功")
    exec_ms: Mapped[int | None] = mapped_column(Integer, comment="执行耗时(ms)")
    affected_rows: Mapped[int | None] = mapped_column(BigInteger, comment="影响行数")
    error: Mapped[str | None] = mapped_column(Text, comment="执行错误")
    sandbox_rolled_back: Mapped[bool | None] = mapped_column(Boolean, comment="沙箱是否已回滚")
    final_sql: Mapped[str | None] = mapped_column(Text, comment="原样 SQL（供人工生产执行）")
    status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default="verifying",
        comment="verifying/verified/pending_gate/ready_for_prod/rejected/blocked/failed",
    )
    trace_id: Mapped[str | None] = mapped_column(String(64), comment="trace")
