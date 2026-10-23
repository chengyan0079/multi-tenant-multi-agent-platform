"""
schemas - 配置 schema 定义（Pydantic v2）

集中声明全部配置项的分组与类型；新增 Agent/插件专属配置时在此扩分组，
由 ConfigManager 统一加载校验。数据库/模型/中间件等按域分组，避免单类膨胀。
"""
from __future__ import annotations

import os
from pydantic import BaseModel, Field


class PostgresSettings(BaseModel):
    """PostgreSQL 连接（checkpointer + 业务 + 长期记忆共用）。"""

    host: str = "localhost"
    port: int = 5432
    user: str = "agent"
    password: str = "agent_pass"
    db: str = "agent_platform"

    @property
    def async_url(self) -> str:
        """拼出 SQLAlchemy asyncpg 连接串。"""
        return f"postgresql+asyncpg://{self.user}:{self.password}@{self.host}:{self.port}/{self.db}"


class RedisSettings(BaseModel):
    """Redis（会话/缓存/队列/HITL）。"""

    host: str = "localhost"
    port: int = 6379
    password: str = ""
    db: int = 0

    @property
    def url(self) -> str:
        auth = f":{self.password}@" if self.password else ""
        return f"redis://{auth}{self.host}:{self.port}/{self.db}"


class MilvusSettings(BaseModel):
    """Milvus（BGE-M3 向量，partition key 租户隔离；语义记忆默认集合）。"""

    host: str = "localhost"
    port: int = 19530
    token: str = ""
    db_name: str = "agent_platform"
    collection: str = "agent_memory"
    dense_dim: int = 1024          # bge-m3 dense 维度
    dense_weight: float = 0.8      # 混合检索 dense 权重（与 sparse_weight 和为 1）
    sparse_weight: float = 0.2     # 混合检索 sparse 权重
    rrf_k: int = 60                # RRF 融合常数


class ModelSettings(BaseModel):
    """四模型分工：LLM / bge-m3 / bge-reranker-v2-m3 / bert-chinese。"""

    api_base: str = "http://localhost:8000/v1"
    api_key: str = ""
    llm_model: str = "deepseek-chat"
    embedding_model: str = "bge-m3"
    reranker_model: str = "bge-reranker-v2-m3"
    classifier_dir: str = ""
    temperature: float = 0.2
    timeout_s: float = 60.0
    max_retries: int = 2


class RagUltraSettings(BaseModel):
    """rag-ultra 适配层接入方式（包导入优先，HTTP 兜底）。"""

    import_path: str = ""
    http_base: str = ""


class SecuritySettings(BaseModel):
    """认证与护栏基础配置（本项目不做登录：身份由上游网关断言，后端只验签+查库授权）。"""

    jwt_secret: str = ""
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 1440
    tenant_header: str = "X-Tenant-Id"
    user_header: str = "X-User-Id"          # 信任头模式下的用户ID头
    trust_headers: bool = False             # True=信任 X-User-Id/X-Tenant-Id（内网/开发，建议 HMAC 防伪造）
    dev_user_id: str = ""                   # 开发身份默认用户ID（非空即零配置本地身份；仍须库中有对应分配）
    dev_tenant_id: str = "dev-tenant"       # 开发身份默认租户ID


class ObservabilitySettings(BaseModel):
    """Langfuse / 可观测。"""

    langfuse_host: str = ""
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""


def _read_env(prefix: str, field: str, default: str) -> str:
    """按 {PREFIX}_{FIELD} 形式读取 env（大小写不敏感），缺失回退 default。"""
    return os.getenv(f"{prefix}_{field.upper()}", default)


class ServiceSettings(BaseModel):
    """服务身份（Nacos 注册 / 健康检查）。"""

    name: str = "agent-platform"
    ip: str = "127.0.0.1"
    port: int = 8000
    version: str = "0.1.0"


class NacosSettings(BaseModel):
    """Nacos 服务发现（仅注册发现，单独命名空间，与配置中心分离）。"""

    enabled: bool = True
    server_addr: str = "http://localhost:8848"
    namespace: str = "public"
    group: str = "DEFAULT_GROUP"
    discover_strict: bool = False  # True=注册失败 fail-fast；False=仅告警继续


class NacosConfigSettings(BaseModel):
    """Nacos 配置中心（独立命名空间 agent-platform，与发现 NACOS_* 分离）。"""

    enabled: bool = True
    server_addr: str = "http://localhost:8848"
    namespace: str = "agent-platform"
    group: str = "SYSTEM"
    user: str = ""
    password: str = ""


class LoggingSettings(BaseModel):
    """日志：等级与文件切片参数。"""

    level: str = "INFO"
    file: str = "logs/app.log"
    size: int = 1024 ** 3
    days: int = 7


class ApiLogSettings(BaseModel):
    """API 调用日志：中间件记录"请求 + 响应"并落库（一行一请求）。"""

    enabled: bool = True          # 是否启用 API 调用日志
    db: bool = True               # 是否落库（关闭则仅打日志）
    max_body: int = 8192          # 请求/响应体记录上限（字节），超出截断
    exclude: list[str] = ["/docs", "/redoc", "/openapi.json", "/admin/health"]  # 不记录的高频路径前缀


class AppSettings(BaseModel):
    """顶层配置：组合各分组。字段值由 ConfigManager 从 env/YAML 注入，不做自动 env 加载。"""

    app_name: str = "agent-platform"
    app_env: str = "dev"

    service: ServiceSettings = Field(default_factory=ServiceSettings)
    nacos: NacosSettings = Field(default_factory=NacosSettings)
    nacos_config: NacosConfigSettings = Field(default_factory=NacosConfigSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    api_log: ApiLogSettings = Field(default_factory=ApiLogSettings)
    postgres: PostgresSettings = Field(default_factory=PostgresSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    milvus: MilvusSettings = Field(default_factory=MilvusSettings)
    model: ModelSettings = Field(default_factory=ModelSettings)
    rag_ultra: RagUltraSettings = Field(default_factory=RagUltraSettings)
    security: SecuritySettings = Field(default_factory=SecuritySettings)
    observability: ObservabilitySettings = Field(default_factory=ObservabilitySettings)
