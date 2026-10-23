"""
settings - ConfigManager：env/YAML + Pydantic 校验 → app_state.settings

加载顺序：env_file(.env) → YAML(可选) → 环境变量覆盖；全部填入 AppSettings 并做 Pydantic 校验，
校验失败即抛错（fail-fast）。其余模块只消费 app_state.settings，不直接读 env。
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict

import yaml
from pydantic import ValidationError

from backend.common.logger import get_logger
from backend.config.schemas import (
    AppSettings,
    LoggingSettings,
    ApiLogSettings,
    MilvusSettings,
    ModelSettings,
    NacosConfigSettings,
    NacosSettings,
    ObservabilitySettings,
    PostgresSettings,
    RagUltraSettings,
    RedisSettings,
    SecuritySettings,
    ServiceSettings,
)

logger = get_logger("config")

# 项目根目录：config/settings.py 位于 <ROOT>/backend/config，向上 2 级到项目根
BASE_DIR = Path(__file__).resolve().parent.parent.parent


def _split_csv(v: str | list) -> list[str]:
    """CSV 字符串 -> list[str]；支持 [*] / [a,b] / ["a","b"](JSON) / a,b / 单值；已是列表则原样返回。"""
    if isinstance(v, list):
        return v
    if not isinstance(v, str):
        return []
    s = v.strip()
    if s.startswith("[") and s.endswith("]"):
        import json

        try:
            parsed = json.loads(s)
            if isinstance(parsed, list):
                return [str(x) for x in parsed]
        except Exception:  # noqa: BLE001
            pass
        inner = s[1:-1]
        return [x.strip().strip('"').strip("'") for x in inner.split(",") if x.strip()]
    return [x.strip() for x in s.split(",") if x.strip()]


class ConfigManager:
    """集中加载与校验配置；application 级别单例由模块级 config 暴露。"""

    def __init__(self, env_file: str = ".env", yaml_file: str = "") -> None:
        self._env_file = env_file
        self._yaml_file = yaml_file

    def _load_env_file(self) -> Dict[str, str]:
        """读取 .env 文件到扁平 dict（仅当文件存在）。环境变量优先级更高，这里不覆盖已有 env。"""
        flat: Dict[str, str] = {}
        if os.path.exists(self._env_file):
            with open(self._env_file, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, _, val = line.partition("=")
                    flat[key.strip()] = val.strip().strip('"').strip("'")
        return flat

    def _load_yaml(self) -> Dict[str, Any]:
        """可选 YAML 覆盖（业务级默认配置），不存在返回空。"""
        if self._yaml_file and os.path.exists(self._yaml_file):
            with open(self._yaml_file, "r", encoding="utf-8") as fh:
                return yaml.safe_load(fh) or {}
        return {}

    def load(self) -> AppSettings:
        """组装并校验配置；失败抛 ValidationError。"""
        flat = self._load_env_file()
        # 环境变量覆盖 .env 文件中的同名项
        merged = {**flat, **{k: v for k, v in os.environ.items() if k in flat or k.isupper()}}
        yaml_cfg = self._load_yaml()

        postgres = PostgresSettings(
            host=merged.get("POSTGRES_HOST", yaml_cfg.get("postgres", {}).get("host", "localhost")),
            port=int(merged.get("POSTGRES_PORT", "5432")),
            user=merged.get("POSTGRES_USER", "agent"),
            password=merged.get("POSTGRES_PASSWORD", "agent_pass"),
            db=merged.get("POSTGRES_DB", "agent_platform"),
        )
        redis = RedisSettings(
            host=merged.get("REDIS_HOST", "localhost"),
            port=int(merged.get("REDIS_PORT", "6379")),
            password=merged.get("REDIS_PASSWORD", ""),
            db=int(merged.get("REDIS_DB", "0")),
        )
        milvus = MilvusSettings(
            host=merged.get("MILVUS_HOST", "localhost"),
            port=int(merged.get("MILVUS_PORT", "19530")),
            token=merged.get("MILVUS_TOKEN", ""),
            db_name=merged.get("MILVUS_DB_NAME", "agent_platform"),
            collection=merged.get("MILVUS_COLLECTION", "agent_memory"),
            dense_dim=int(merged.get("MILVUS_DENSE_DIM", "1024")),
            dense_weight=float(merged.get("MILVUS_DENSE_WEIGHT", "0.8")),
            sparse_weight=float(merged.get("MILVUS_SPARSE_WEIGHT", "0.2")),
            rrf_k=int(merged.get("MILVUS_RRF_K", "60")),
        )
        model = ModelSettings(
            api_base=merged.get("LLM_API_BASE", "http://localhost:8000/v1"),
            api_key=merged.get("LLM_API_KEY", ""),
            llm_model=merged.get("LLM_MODEL", "deepseek-chat"),
            embedding_model=merged.get("EMBEDDING_MODEL", "bge-m3"),
            reranker_model=merged.get("RERANKER_MODEL", "bge-reranker-v2-m3"),
            classifier_dir=merged.get("CLASSIFIER_DIR", ""),
        )
        rag_ultra = RagUltraSettings(
            import_path=merged.get("RAG_ULTRA_IMPORT_PATH", ""),
            http_base=merged.get("RAG_ULTRA_HTTP_BASE", ""),
        )
        security = SecuritySettings(
            jwt_secret=merged.get("JWT_SECRET", ""),
            jwt_algorithm=merged.get("JWT_ALGORITHM", "HS256"),
            jwt_expire_minutes=int(merged.get("JWT_EXPIRE_MINUTES", "1440")),
            tenant_header=merged.get("TENANT_HEADER", "X-Tenant-Id"),
            user_header=merged.get("USER_HEADER", "X-User-Id"),
            trust_headers=merged.get("TRUST_HEADERS", "False").lower() == "true",
            dev_user_id=merged.get("DEV_USER_ID", ""),
            dev_tenant_id=merged.get("DEV_TENANT_ID", "dev-tenant"),
        )
        observability = ObservabilitySettings(
            langfuse_host=merged.get("LANGFUSE_HOST", ""),
            langfuse_public_key=merged.get("LANGFUSE_PUBLIC_KEY", ""),
            langfuse_secret_key=merged.get("LANGFUSE_SECRET_KEY", ""),
        )
        service = ServiceSettings(
            name=merged.get("SERVICE_NAME", "agent-platform"),
            ip=merged.get("SERVICE_IP", "127.0.0.1"),
            port=int(merged.get("PORT", "8000")),
            version=merged.get("VERSION", "0.1.0"),
        )
        nacos = NacosSettings(
            enabled=merged.get("NACOS_ENABLED", "True").lower() == "true",
            server_addr=merged.get("NACOS_SERVER_ADDR", "http://localhost:8848"),
            namespace=merged.get("NACOS_NAMESPACE", "public"),
            group=merged.get("NACOS_GROUP", "DEFAULT_GROUP"),
            discover_strict=merged.get("NACOS_DISCOVER_STRICT", "False").lower() == "true",
        )
        nacos_config = NacosConfigSettings(
            enabled=merged.get("NACOS_CONFIG_ENABLED", "True").lower() == "true",
            server_addr=merged.get("NACOS_CONFIG_SERVER_ADDR", "http://localhost:8848"),
            namespace=merged.get("NACOS_CONFIG_NAMESPACE", "agent-platform"),
            group=merged.get("NACOS_CONFIG_GROUP", "SYSTEM"),
            user=merged.get("NACOS_CONFIG_USER", ""),
            password=merged.get("NACOS_CONFIG_PASSWORD", ""),
        )
        logging_cfg = LoggingSettings(
            level=merged.get("LOG_LEVEL", "INFO"),
            file=merged.get("LOG_FILE", "logs/app.log"),
            size=int(merged.get("LOG_SIZE", str(1024 ** 3))),
            days=int(merged.get("LOG_FILE_DAYS", "7")),
        )
        api_log_cfg = ApiLogSettings(
            enabled=merged.get("API_LOG_ENABLED", "True").lower() == "true",
            db=merged.get("API_LOG_DB", "True").lower() == "true",
            max_body=int(merged.get("API_LOG_MAX_BODY", "8192")),
            exclude=_split_csv(merged.get("API_LOG_EXCLUDE",
                "/docs,/redoc,/openapi.json,/admin/health")),
        )

        settings = AppSettings(
            app_name=merged.get("APP_NAME", "agent-platform"),
            app_env=merged.get("APP_ENV", "dev"),
            service=service,
            nacos=nacos,
            nacos_config=nacos_config,
            logging=logging_cfg,
            api_log=api_log_cfg,
            postgres=postgres,
            redis=redis,
            milvus=milvus,
            model=model,
            rag_ultra=rag_ultra,
            security=security,
            observability=observability,
        )
        try:
            settings.model_validate(settings.model_dump())
        except ValidationError as exc:
            logger.error(f"配置校验失败: {exc}")
            raise
        logger.info(f"配置加载完成 env={settings.app_env}")
        return settings


config: AppSettings = ConfigManager().load()
