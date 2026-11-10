"""model_registry 表：模型配置注册表（平台级全局），按 model_type 区分，取 enabled 且 sort_order 最小者。"""

from typing import Optional

from sqlalchemy.orm import Mapped, mapped_column

from sqlalchemy import (
    BigInteger,
    Boolean,
    Float,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)

from backend.data.postgres.base import AuditUserOnlyMixin, Base


class ModelRegistry(AuditUserOnlyMixin, Base):
    """模型配置注册表（平台级全局资源，不分租户）。"""

    __tablename__ = "agent_model_registry"
    __table_args__ = (
        UniqueConstraint("model_type", "name", name="uq_model_registry_type_name"),
        {"comment": "模型配置注册表（平台级全局资源，不分租户）"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, comment="主键（代理键）")
    model_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        index=True,
        comment="用途分类：llm / embedding / reranker / classifier",
    )
    name: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        comment="模型标识（如 deepseek-chat / bge-m3）",
    )
    provider: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
        comment="厂商（openai / dashscope / local），可空",
    )
    base_url: Mapped[Optional[str]] = mapped_column(
        String(512),
        nullable=True,
        comment="远程 API 基址；本地模型改用 endpoint_path",
    )
    api_key: Mapped[Optional[str]] = mapped_column(
        String(512),
        nullable=True,
        comment="API 密钥（敏感，可空）",
    )
    endpoint_path: Mapped[Optional[str]] = mapped_column(
        String(512),
        nullable=True,
        comment="本地模型路径（classifier_dir 类）",
    )
    temperature: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True,
        comment="LLM 采样温度（仅 llm 用）",
    )
    timeout_s: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True,
        comment="调用超时（秒）",
    )
    max_retries: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="失败重试次数",
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("true"),
        comment="是否启用",
    )
    sort_order: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("0"),
        comment="同类排序（前端下拉 / 默认选择）",
    )
    description: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="备注",
    )
