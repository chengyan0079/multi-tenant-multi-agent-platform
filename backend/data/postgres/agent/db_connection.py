"""数据库连接（数据源）表（租户级）：供工具按 connection_id 动态连接，不固定绑定。"""

from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, Integer, String, Text, UniqueConstraint, UUID, text
from sqlalchemy.orm import Mapped, mapped_column

from backend.data.postgres.base import TimestampMixin, Base


class AgentDbConnection(TimestampMixin, Base):
    """租户级数据库数据源（多行；工具运行时按 connection_id 选择）。"""

    __tablename__ = "agent_db_connection"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_db_conn_tenant_name"),
        {"comment": "数据库连接（数据源，租户级）"},
    )

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
        comment="主键（UUID）",
    )
    tenant_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, index=True, comment="租户ID"
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False, comment="数据源名")
    db_type: Mapped[str] = mapped_column(
        String(16), nullable=False, comment="mysql / postgresql"
    )
    host: Mapped[str] = mapped_column(String(255), nullable=False, comment="主机")
    port: Mapped[int] = mapped_column(Integer, nullable=False, comment="端口")
    username: Mapped[str] = mapped_column(String(128), nullable=False, comment="用户名")
    password: Mapped[str] = mapped_column(
        String(512), nullable=False, comment="密码（开发期明文；生产必须加密）"
    )
    database: Mapped[str] = mapped_column(String(128), nullable=False, comment="数据库名")
    schema_name: Mapped[str | None] = mapped_column(String(128), comment="schema（PostgreSQL）")
    readonly: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true"), comment="只读标志（强制只读）"
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true"), comment="是否启用"
    )
    env: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        server_default=text("'prod'"),
        comment="环境：prod / staging / sandbox",
    )
    remark: Mapped[str | None] = mapped_column(Text, comment="备注")
