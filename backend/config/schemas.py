"""配置 schema 定义（pydantic-settings v2）：各分组映射 .env 扁平变量。"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import quote, urlunparse

from typing import Optional

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
    # 可用环境变量 POSTGRES_SEARCH_PATH 覆盖（存量库可指回旧 schema）。
    search_path: str = "unified_schemas"
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

        netloc = (
            f"{quote(self.user, safe='')}:{quote(self.password, safe='')}@{self.host}:{self.port}"
        )
        return urlunparse(("amqp", netloc, f"/{self.vhost}", "", "", ""))


class SchedulerSettings(BaseSettings):
    """定时任务（通用定时器；默认随应用启动，不依赖 broker）。"""

    model_config = SettingsConfigDict(**_COMMON, env_prefix="SCHEDULER_")

    escalation_timeout_min: int = 30  # HITL 转人工超时阈值（分钟），可调
    resume_timeout_min: int = 10  # resume 评审 processing 超时阈值（分钟，=600s），可调
    scan_interval: int = 60  # 默认扫描间隔（秒），各 job 可独立覆盖
    config_refresh_interval: int = 5  # 跨副本配置刷新信号轮询间隔（秒）


class MilvusSettings(BaseSettings):
    """Milvus（BGE-M3 向量，partition key 租户隔离；RAG 文档向量集合）。"""

    model_config = SettingsConfigDict(**_COMMON, env_prefix="MILVUS_")

    host: str = "localhost"
    port: int = 19530
    token: str = ""
    db_name: str = "agent_platform"
    collection: str = "agent_rag_docs"
    dense_dim: int = 1024  # bge-m3 dense 维度
    dense_weight: float = 0.8  # 混合检索 dense 权重（与 sparse_weight 和为 1）
    sparse_weight: float = 0.2  # 混合检索 sparse 权重
    rrf_k: int = 60  # RRF 融合常数


class QaSettings(BaseSettings):
    """智能问答 Agent 的检索 / 阈值 / 窗口参数（可用 .env 的 QA_* 覆盖）。"""

    model_config = SettingsConfigDict(**_COMMON, env_prefix="QA_")

    max_upload_mb: int = 200  # 单文件大小上限（MB）
    auto_parse: bool = True  # 上传成功后自动入队 qa.parse（关则只落库，需手动触发解析）

    precise_top_k: int = 5  # PRECISE 单路检索召回数
    vague_top_k: int = 8  # VAGUE（HyDE）检索召回数
    broad_per_query_top_k: int = 5  # BROAD 多查询每个子查询召回数
    merge_top_k: int = 5  # BROAD 合并后取前 N
    high_confidence_threshold: float = 0.75  # 高置信度判定阈值（精排分数）
    web_search_max_results: int = 5  # Web 搜索结果上限
    summary_trigger_turns: int = 6  # 用户提问轮数达到即触发摘要压缩

    # —— 文档解析 / 分块（backend/rag，参考 thy-edu-agent core/document_splitters）——
    chunk_size: int = 512  # PDF/TXT 递归切分块大小（无父子片时的兜底）
    chunk_overlap: int = 64  # PDF/TXT 重叠
    md_chunk_size: int = 600  # Markdown 两阶段切分块大小
    md_chunk_overlap: int = 60  # Markdown 重叠
    # —— 父子片（small-to-big，参照 RAG-Ultra）——
    parent_chunk_size: int = 1200  # 父片大小：命中子片后回填给 LLM 的完整上下文
    parent_chunk_overlap: int = 100  # 父片重叠
    child_chunk_size: int = 300  # 子片大小：实际参与向量召回
    child_chunk_overlap: int = 20  # 子片重叠
    parent_context_by_highlight: bool = True  # 生成节点用"父片内高亮子片"替代纯子片
    index_batch_size: int = 32  # 单批向量化/写入条数
    # —— 检索 / 精排 ——
    recall_top_k: int = 10  # 混合召回候选数（精排前）
    rerank_top_k: int = 3  # 精排后保留条数
    rerank_max_input_chars: int = 1200  # 单条候选送入精排的最大字符数


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
    """Langfuse / 可观测（LANGFUSE_BASE_URL / PUBLIC_KEY / SECRET_KEY）。"""

    model_config = SettingsConfigDict(**_COMMON, env_prefix="LANGFUSE_")

    langfuse_base_url: str = ""  # LANGFUSE_BASE_URL，如 http://localhost:3100
    langfuse_public_key: str = ""  # LANGFUSE_PUBLIC_KEY
    langfuse_secret_key: str = ""  # LANGFUSE_SECRET_KEY


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


class NacosAuthMixin:
    """Nacos 鉴权字段（3.x 默认开启鉴权，需透传；二选一：user/password 或 access_key/secret_key）。"""

    user: str = ""
    password: str = ""
    access_key: str = ""
    secret_key: str = ""


class NacosSettings(BaseSettings, NacosAuthMixin):
    """Nacos 服务发现（仅注册发现，单独命名空间，与配置中心分离）。

    Nacos 3.x 默认开启鉴权，发现侧同样需 user/password（或 access_key/secret_key）。
    """

    model_config = SettingsConfigDict(**_COMMON, env_prefix="NACOS_")

    enabled: bool = True
    server_addr: str = "http://localhost:8848"
    namespace: str = "public"
    group: str = "DEFAULT_GROUP"
    discover_strict: bool = True  # True=注册失败 fail-fast；False=仅告警继续


class NacosConfigSettings(BaseSettings, NacosAuthMixin):
    """Nacos 配置中心（独立命名空间 agent-platform，与发现 NACOS_* 分离）。"""

    model_config = SettingsConfigDict(**_COMMON, env_prefix="NACOS_CONFIG_")

    enabled: bool = True
    server_addr: str = "http://localhost:8848"
    namespace: str = "3d523e88-a17f-4a90-88c5-d31793405818"
    group: str = "SYSTEM"


class NacosAISettings(BaseSettings, NacosAuthMixin):
    """Nacos AI 客户端（MCP Server / Agent Card / Prompt / Skill）。

    需 Nacos 服务端 >= 3.1.0；AI 资产与配置中心同处 agent-platform 命名空间。
    """

    model_config = SettingsConfigDict(**_COMMON, env_prefix="NACOS_AI_")

    enabled: bool = True
    server_addr: str = "http://localhost:8848"
    namespace: str = "3d523e88-a17f-4a90-88c5-d31793405818"
    group: str = "DEFAULT_GROUP"

    # ---- 发布本平台 MCP Server 到 Nacos AI（release_mcp_server）----
    # 需 Nacos 服务端 >= 3.1.0。Agent Card / Prompt / Skill 暂未对接（等 SDK 更新；Prompt 走配置中心）。
    # publish_mcp 默认开启：启用 Nacos AI 即发布；若要只连不发布设 False。
    publish_mcp: bool = True
    mcp_server_name: str = "agent-platform-mcp"
    mcp_protocol: str = "mcp-streamable"
    mcp_front_protocol: str = "mcp-streamable"
    mcp_description: str = "多租户多智能体协作平台 MCP Server"
    mcp_version: str = "1.0.0"
    mcp_endpoint_path: str = "/mcp"
    mcp_capabilities: list[str] = ["TOOL"]
    mcp_tools: list[dict] = []
    # True=发布/加载失败 fail-fast（默认阻断启动）；False=仅告警继续
    strict: bool = True

    # ---- 从 Nacos AI 加载远程资产（Agent Card / MCP Server）----
    # SDK 仅支持按名查询/订阅（无 list 能力），故用 allow-list 指定名称清单。
    # subscribe_remote=True 走 subscribe_* 长连接实时更新；False 则启动期 get_* 拉一次快照。
    # 默认均为空：启用 Nacos AI 也不会自动拉取任何外部资产（安全默认）。
    load_agent_cards: list[str] = []
    load_mcp_servers: list[str] = []
    subscribe_remote: bool = True
    agent_card_version: Optional[str] = None
    # 加载远程 MCP Server 时按此版本拉取（None=最新）；与发布版本 mcp_version(默认 1.0.0) 区分，
    # 避免与上面的发布字段同名导致后者被覆盖为 None。
    load_mcp_version: Optional[str] = None
    agent_card_registration_type: str = "service"


class LoggingSettings(BaseSettings):
    """日志：等级与文件切片参数。"""

    model_config = SettingsConfigDict(**_COMMON, env_prefix="LOG_")

    level: str = "INFO"
    file: str = "logs/app.log"  # 相对路径以项目根目录为基准（见 common/logger.py）
    size: int = 1024**3
    days: int = 7


class ApiLogSettings(BaseSettings):
    """API 调用日志：中间件记录"请求 + 响应"并落库（一行一请求）。

    默认只记元数据（方法/路径/状态/耗时/身份/请求头），不采集请求体与响应体：
    记录体需要缓冲整个请求/响应，且单行可达数十 KB，是表膨胀的主因。
    """

    model_config = SettingsConfigDict(**_COMMON, env_prefix="API_LOG_")

    enabled: bool = True  # 是否启用 API 调用日志
    db: bool = True  # 是否落库（关闭则仅打日志）
    save_body: bool = False  # 是否采集请求/响应体（关闭后中间件不缓冲 body）
    max_body: int = 8192  # 采集体时的上限（字节），超出截断；save_body=False 时不生效
    # .env 用逗号分隔字符串（/docs,/redoc,...）；这里存原始串，由 exclude 属性解析为列表。
    # 健康检查在 /api/v1/health（免鉴权，探针高频调用），不落库；
    # API 调用日志查询端点自身不落库（自查询无意义，且污染日志表）。
    exclude_raw: str = "/docs,/redoc,/openapi.json,/api/v1/health,/api/v1/admin/audit/api-logs"

    @property
    def exclude(self) -> list[str]:
        """逗号分隔的高频路径前缀列表（这些路径不记录 API 日志）。"""
        return [x.strip() for x in self.exclude_raw.split(",") if x.strip()]


class ModelSettings(BaseSettings):
    """本地模型根目录（registry 的 endpoint_path 为相对路径时，拼到此目录下解析）。"""

    model_config = SettingsConfigDict(**_COMMON, env_prefix="MODEL_")

    root: str = str(BASE_DIR)  # 默认项目根；endpoint_path 相对路径以此为基


class AppSettings(BaseSettings):
    """顶层配置：组合各分组。

    顶层字段（app_name / app_env）直接映射 .env（APP_NAME / APP_ENV）；
    各分组子模型各自按 env_prefix / alias 读取 .env，分组访问方式不变
    （如 config.postgres.host）。
    """

    model_config = SettingsConfigDict(**_COMMON)

    app_name: str = "agent-platform"
    app_env: str = "dev"

    model: ModelSettings = Field(default_factory=ModelSettings)

    service: ServiceSettings = Field(default_factory=ServiceSettings)
    nacos: NacosSettings = Field(default_factory=NacosSettings)
    nacos_config: NacosConfigSettings = Field(default_factory=NacosConfigSettings)
    nacos_ai: NacosAISettings = Field(default_factory=NacosAISettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    api_log: ApiLogSettings = Field(default_factory=ApiLogSettings)
    postgres: PostgresSettings = Field(default_factory=PostgresSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    broker: BrokerSettings = Field(default_factory=BrokerSettings)
    scheduler: SchedulerSettings = Field(default_factory=SchedulerSettings)
    milvus: MilvusSettings = Field(default_factory=MilvusSettings)
    minio: MinioSettings = Field(default_factory=MinioSettings)
    qa: QaSettings = Field(default_factory=QaSettings)
    security: SecuritySettings = Field(default_factory=SecuritySettings)
    observability: ObservabilitySettings = Field(default_factory=ObservabilitySettings)
