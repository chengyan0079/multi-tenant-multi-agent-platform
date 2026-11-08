"""文件元数据表（MinIO 对象引用）。

设计说明：
- 一行 = 一个上传文件版本；同名文件重复上传时 `file_version` 递增，`object_key` 唯一；
- `tenant_id` 是隔离边界：普通用户/租户管理员只能看到本租户文件，超管（tenant_id=NULL）
  可看全部；超管自己上传的文件 tenant_id 为 NULL（平台级）；
- `uploader_user_id` 显式记录上传用户；审计列（create_user_id 等）由写库时统一注入；
- 只存元数据，文件本体在 MinIO（bucket + object_key 可定位）。
"""
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
        String(16), nullable=False,
        default="pending", server_default=text("'pending'"),
        # server_default 必须保留：FileDao 用裸 SQL INSERT 且不传该列，依赖库默认值
        comment="解析状态：pending 未解析 / parsing 解析中 / parsed 已解析 / failed 解析失败",
    )
