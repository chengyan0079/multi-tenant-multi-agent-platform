"""
schemas - 配置 schema 定义（pydantic-settings v2）

集中声明配置分组；每个子模型继承 BaseSettings，通过 env_prefix / validation_alias
直接映射 .env 中的扁平变量（POSTGRES_HOST 等），不再手工拼装。
新增 Agent/插件配置时在此扩分组即可。
"""
from __future__ import annotations

from pathlib import Path
from urllib.parse import quote, urlunparse

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL

BASE_DIR = Path(__file__).resolve().parent.parent.parent
_ENV_FILE = str(BASE_DIR / ".env")

# 公共配置：自动加载 .env，大小写不敏感，未知变量忽略（便于多项目共用同一 .env）
_COMMON = dict(
    env_file=_ENV_FILE,
    env_file_encoding="utf-8",
    case_sensitive=False,
    extra="ignore",
)


class PostgresSettings(BaseSettings):
    """PostgreSQL 连接（checkpointer + 业务 + 长期记忆共用）。"""

    model_config = SettingsConfigDict(**_COMMON, env_prefix="POSTGRES_")

    host: str = "localhost"
    port: int = 5432
    user: str = "postgres"
    password: str = ""
    db: str = "agent_platform"
    # 专属 schema：schema.sql 把所有表建在此 schema 下，连接时通过 asyncpg
    # server_settings 设置 search_path，否则 ORM/DAO 裸 SQL 找不到表。
    # 可用环境变量 POSTGRES_SEARCH_PATH 覆盖。
    search_path: str = "agent_platform"
    # SQL 调试日志（POSTGRES_SQL_DEBUG）：开启后把实际执行的 SQL（参数内联成可执行语句）
    # 打到 DEBUG 日志；仅排查用，默认关，避免生产泄露参数与性能开销。
    sql_debug: bool = False

    @property
    def async_url(self) -> str:
        """拼出 SQLAlchemy asyncpg 连接串（search_path 由 server_settings 注入）。

        用 sqlalchemy.URL.create 构造，用户名/密码里的 @、: 会被自动转义，
        避免裸字符串拼接受特殊字符密码影响。
        """
        # render_as_string(hide_password=False)：str(URL) 默认会把密码打成 ***，
        # 连接串一旦脱敏，create_async_engine 就拿不到真密码，必须关掉。
        return URL.create(
            "postgresql+asyncpg",
            username=self.user,
            password=self.password,
            host=self.host,
            port=self.port,
            database=self.db,
        ).render_as_string(hide_password=False)


class RedisSettings(BaseSettings):
    """Redis（会话/缓存/队列/HITL）。"""

    model_config = SettingsConfigDict(**_COMMON, env_prefix="REDIS_")

    host: str = "localhost"
    port: int = 6379
    password: str = ""
    db: int = 1

    @property
    def url(self) -> str:
        """拼出 Redis 连接串；密码经 quote 转义，含 @ / : 也不破坏格式。

        无密码时省略认证段（redis://host:port/db）。
        """
        if self.password:
            netloc = f":{quote(self.password, safe='')}@{self.host}:{self.port}"
        else:
            netloc = f"{self.host}:{self.port}"
        return urlunparse(("redis", netloc, f"/{self.db}", "", "", ""))


class BrokerSettings(BaseSettings):
    """RabbitMQ（消息队列 broker；独立中间件部署，见 docs/消息队列对接设计）。

    启用开关默认 False：无 broker 时不注册 Manager，避免阻断启动（fail-fast 回滚）。
    """

    model_config = SettingsConfigDict(**_COMMON, env_prefix="RABBITMQ_")

    enabled: bool = False
    host: str = "localhost"
    port: int = 5672
    user: str = "agent"
    password: str = "agent"
    vhost: str = "agent_platform"

    @property
    def url(self) -> str:
        """拼出 AMQP 连接串；密码经 quote 转义。"""
        from urllib.parse import quote, urlunparse

        netloc = f"{quote(self.user, safe='')}:{quote(self.password, safe='')}@{self.host}:{self.port}"
        return urlunparse(("amqp", netloc, f"/{self.vhost}", "", "", ""))


class SchedulerSettings(BaseSettings):
    """定时任务（HITL 超时扫描；与 broker 同启用）。"""

    model_config = SettingsConfigDict(**_COMMON, env_prefix="SCHEDULER_")

    escalation_timeout_min: int = 30  # 超时阈值（分钟），可调
    scan_interval: int = 60  # 扫描间隔（秒），可调


class MilvusSettings(BaseSettings):
    """Milvus（BGE-M3 向量，partition key 租户隔离；语义记忆默认集合）。"""

    model_config = SettingsConfigDict(**_COMMON, env_prefix="MILVUS_")

    host: str = "localhost"
    port: int = 19530
    token: str = ""
    db_name: str = "agent_platform"
    collection: str = "agent_memory"
    dense_dim: int = 1024          # bge-m3 dense 维度
    dense_weight: float = 0.8      # 混合检索 dense 权重（与 sparse_weight 和为 1）
    sparse_weight: float = 0.2     # 混合检索 sparse 权重
    rrf_k: int = 60                # RRF 融合常数


class RagSettings(BaseSettings):
    """RAG 适配层接入方式（MCP 优先，包导入 / HTTP 兜底）。

    mcp_url：对外暴露的 MCP 服务地址（FastMCP streamable-http，默认
        http://127.0.0.1:8766/mcp）。配置后检索走 MCP 工具，不再依赖本仓库内代码。
    """

    model_config = SettingsConfigDict(**_COMMON, env_prefix="RAG_")

    mcp_url: str = ""
    import_path: str = ""
    http_base: str = ""


class SecuritySettings(BaseSettings):
    """认证基础配置（token 单源：身份只来自 JWT，不读任何身份头 / 开发兜底，见设计文档 §4.1）。

    已删除：TENANT_HEADER / USER_HEADER / TRUST_HEADERS / DEV_USER_ID / DEV_TENANT_ID
    —— 身份一律从 Authorization: Bearer <JWT> 解析，不信任请求头、不留开发默认身份。
    """

    model_config = SettingsConfigDict(**_COMMON, populate_by_name=True)

    jwt_secret: str = Field(default="", validation_alias="JWT_SECRET")
    jwt_algorithm: str = Field(default="HS256", validation_alias="JWT_ALGORITHM")
    jwt_expire_minutes: int = Field(default=1440, validation_alias="JWT_EXPIRE_MINUTES")
    # 登录会话在 Redis 的 TTL（秒）；超过该时长无任何请求即失效，每次请求滑动续期
    session_ttl_seconds: int = Field(default=900, validation_alias="SESSION_TTL_SECONDS")


class ObservabilitySettings(BaseSettings):
    """Langfuse / 可观测。"""

    model_config = SettingsConfigDict(**_COMMON, env_prefix="LANGFUSE_")

    langfuse_host: str = ""
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""


class MinioSettings(BaseSettings):
    """MinIO（S3 兼容对象存储：文档/媒体/轨迹产物等）。

    仅承载配置；实际客户端（minio/aioboto3 等）由各使用方按需构造。
    """

    model_config = SettingsConfigDict(**_COMMON, env_prefix="MINIO_")

    endpoint: str = "http://localhost:9000"  # 含 scheme，如 http://localhost:9000
    bucket: str = "agent-platform"
    access_key: str = "minioadmin"
    secret_key: str = "minioadmin"

    @property
    def secure(self) -> bool:
        """endpoint 是否 https（S3 客户端 secure 标记）。"""
        return self.endpoint.startswith("https")

    @property
    def host(self) -> str:
        """去掉 scheme 后的 host:port（S3 客户端 endpoint 入参）。"""
        return self.endpoint.split("://", 1)[-1]


class ServiceSettings(BaseSettings):
    """服务身份（Nacos 注册 / 健康检查 / API 文档）。"""

    model_config = SettingsConfigDict(**_COMMON, populate_by_name=True)

    name: str = Field(default="agent-platform", validation_alias="SERVICE_NAME")
    ip: str = Field(default="127.0.0.1", validation_alias="SERVICE_IP")
    port: int = Field(default=8000, validation_alias="PORT")
    version: str = Field(default="0.1.0", validation_alias="VERSION")
    docs_enabled: bool = Field(default=False, validation_alias="DOCS_ENABLED")


class NacosSettings(BaseSettings):
    """Nacos 服务发现（仅注册发现，单独命名空间，与配置中心分离）。"""

    model_config = SettingsConfigDict(**_COMMON, env_prefix="NACOS_")

    enabled: bool = True
    server_addr: str = "http://localhost:8848"
    namespace: str = "public"
    group: str = "DEFAULT_GROUP"
    discover_strict: bool = True  # True=注册失败 fail-fast；False=仅告警继续


class NacosConfigSettings(BaseSettings):
    """Nacos 配置中心（独立命名空间 agent-platform，与发现 NACOS_* 分离）。"""

    model_config = SettingsConfigDict(**_COMMON, env_prefix="NACOS_CONFIG_")

    enabled: bool = True
    server_addr: str = "http://localhost:8848"
    namespace: str = "3d523e88-a17f-4a90-88c5-d31793405818"
    group: str = "SYSTEM"
    user: str = ""
    password: str = ""


class LoggingSettings(BaseSettings):
    """日志：等级与文件切片参数。"""

    model_config = SettingsConfigDict(**_COMMON, env_prefix="LOG_")

    level: str = "INFO"
    file: str = "logs/app.log"    # 相对路径以项目根目录为基准（见 common/logger.py）
    size: int = 1024 ** 3
    days: int = 7


class ApiLogSettings(BaseSettings):
    """API 调用日志：中间件记录"请求 + 响应"并落库（一行一请求）。

    默认只记元数据（方法/路径/状态/耗时/身份/请求头），不采集请求体与响应体：
    记录体需要缓冲整个请求/响应，且单行可达数十 KB，是表膨胀的主因。
    """

    model_config = SettingsConfigDict(**_COMMON, env_prefix="API_LOG_")

    enabled: bool = True          # 是否启用 API 调用日志
    db: bool = True               # 是否落库（关闭则仅打日志）
    save_body: bool = False       # 是否采集请求/响应体（关闭后中间件不缓冲 body）
    max_body: int = 8192          # 采集体时的上限（字节），超出截断；save_body=False 时不生效
    # .env 用逗号分隔字符串（/docs,/redoc,...）；这里存原始串，由 exclude 属性解析为列表。
    # 健康检查在 /api/v1/health（免鉴权，探针高频调用），不落库；
    # API 调用日志查询端点自身不落库（自查询无意义，且污染日志表）。
    exclude_raw: str = "/docs,/redoc,/openapi.json,/api/v1/health,/api/v1/admin/audit/api-logs"

    @property
    def exclude(self) -> list[str]:
        """逗号分隔的高频路径前缀列表（这些路径不记录 API 日志）。"""
        return [x.strip() for x in self.exclude_raw.split(",") if x.strip()]


class FileSettings(BaseSettings):
    """文件上传限制（可通过 .env 的 FILE_MAX_UPLOAD_MB 覆盖）。"""

    model_config = SettingsConfigDict(**_COMMON, env_prefix="FILE_")

    max_upload_mb: int = 200  # 单文件大小上限（MB）


class AppSettings(BaseSettings):
    """顶层配置：组合各分组。

    顶层字段（app_name / app_env）直接映射 .env（APP_NAME / APP_ENV）；
    各分组子模型各自按 env_prefix / alias 读取 .env，分组访问方式不变
    （如 config.postgres.host）。
    """

    model_config = SettingsConfigDict(**_COMMON)

    app_name: str = "agent-platform"
    app_env: str = "dev"

    service: ServiceSettings = Field(default_factory=ServiceSettings)
    nacos: NacosSettings = Field(default_factory=NacosSettings)
    nacos_config: NacosConfigSettings = Field(default_factory=NacosConfigSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    api_log: ApiLogSettings = Field(default_factory=ApiLogSettings)
    postgres: PostgresSettings = Field(default_factory=PostgresSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    broker: BrokerSettings = Field(default_factory=BrokerSettings)
    scheduler: SchedulerSettings = Field(default_factory=SchedulerSettings)
    milvus: MilvusSettings = Field(default_factory=MilvusSettings)
    minio: MinioSettings = Field(default_factory=MinioSettings)
    file: FileSettings = Field(default_factory=FileSettings)
    rag: RagSettings = Field(default_factory=RagSettings)
    security: SecuritySettings = Field(default_factory=SecuritySettings)
    observability: ObservabilitySettings = Field(default_factory=ObservabilitySettings)
