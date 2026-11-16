"""文件元数据表（agent_file）：一行一版本，tenant_id 隔离，文件本体在 MinIO。"""

from __future__ import annotations

from sqlalchemy import BigInteger, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from backend.data.postgres.base import AuditMixin, Base


class AgentFile(AuditMixin, Base):
    """文件元数据（一个逻辑文件多版本，每版本一行）。

    版本化规则：
    - `file_uuid` 跨版本不变，是逻辑文件的稳定标识；重命名文件名前缀用它；
    - `original_name` 是用户上传时的原始文件名（展示用）；判重按 `lower(trim(original_name))`；
    - 同名文件重复上传 → `file_version` 递增；内容与最新版完全一致 → 拦截（不落库）。
    """

    __tablename__ = "agent_file"
    __table_args__ = (
        Index("uk_agent_file_object_key", "object_key", unique=True),
        Index("uk_agent_file_uuid_version", "file_uuid", "file_version", unique=True),
        Index("idx_agent_file_tenant_create", "tenant_id", "create_at"),
        Index(
            "idx_agent_file_tenant_user_name",
            "tenant_id",
            "uploader_user_id",
            text("lower(trim(original_name))"),
        ),
        Index("idx_agent_file_thread", "thread_id"),
        Index("idx_agent_file_request", "request_id"),
        {"comment": "文件元数据（MinIO 对象引用，按租户隔离；同一逻辑文件多版本）"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, comment="主键")
    tenant_id: Mapped[int | None] = mapped_column(
        BigInteger, comment="上传租户ID（隔离边界；超管上传为 NULL 表示平台级）"
    )
    uploader_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="上传用户ID")
    original_name: Mapped[str] = mapped_column(
        String(255), nullable=False, comment="原始文件名（展示用；判重按 lower(trim())）"
    )
    file_uuid: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="逻辑文件 uuid（跨版本不变；重命名前缀）"
    )
    file_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="重命名后的存储文件名：{file_uuid}_{user_id}_v{版本}_upload.pdf",
    )
    object_key: Mapped[str] = mapped_column(String(512), nullable=False, comment="MinIO 对象键")
    bucket: Mapped[str] = mapped_column(String(128), nullable=False, comment="MinIO 桶名")
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="文件大小（字节）")
    content_type: Mapped[str | None] = mapped_column(String(128), comment="MIME 类型")
    file_ext: Mapped[str | None] = mapped_column(String(32), comment="扩展名（含点，如 .pdf）")
    file_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, comment="同名文件版本号（从 1 递增）"
    )
    checksum: Mapped[str | None] = mapped_column(String(64), comment="内容校验（sha256 十六进制）")
    remark: Mapped[str | None] = mapped_column(String(512), comment="备注")
    parse_status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="pending",
        server_default=text("'pending'"),
        # server_default 必须保留：FileDao 用裸 SQL INSERT 且不传该列，依赖库默认值
        comment="解析状态：pending 未解析 / parsing 解析中 / parsed 已解析 / failed 解析失败",
    )
    # ---- Agent 业务归属（db_review 等；可空，兼容通用文件上传）----
    agent_type: Mapped[str | None] = mapped_column(
        String(64), comment="归属 Agent 类型（如 db_review）"
    )
    file_kind: Mapped[str | None] = mapped_column(
        String(16), comment="文件用途：script 脚本 / drill 回滚演练 / attachment 附件"
    )
    thread_id: Mapped[str | None] = mapped_column(String(64), comment="关联会话/线程ID")
    request_id: Mapped[str | None] = mapped_column(String(64), comment="关联变更单ID")
    db_type: Mapped[str | None] = mapped_column(
        String(16), comment="目标库类型（mysql/postgresql），用于脚本方言校验"
    )
