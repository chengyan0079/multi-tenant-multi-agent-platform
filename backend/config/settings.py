"""配置单例：AppSettings() 校验 .env 后导出 config 供全局消费。"""

from __future__ import annotations

import os
from pathlib import Path

from backend.common.logger import get_logger
from backend.config.schemas import AppSettings

logger = get_logger("config")

# 项目根目录：config/settings.py 位于 <ROOT>/backend/config，向上 2 级到项目根
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# 显式加载项目根 .env，保证无论从哪个工作目录启动都能读到配置（含 LANGFUSE_* 等）。
# override=False：不覆盖进程已有的环境变量（如 shell 已 export 的变量）。
try:
    from dotenv import load_dotenv

    load_dotenv(BASE_DIR / ".env", override=False)
except Exception:  # python-dotenv 缺失时跳过，回退到进程已有环境变量
    pass

# 模块级单例：导入即加载并校验（校验失败直接抛错 fail-fast）
config: AppSettings = AppSettings()

# 兜底：嵌套的 ObservabilitySettings 在部分 pydantic-settings 版本下不会自动从
# os.environ / env_file 读取带 LANGFUSE_ 前缀的变量，这里直接按变量名补齐。
_obs = config.observability
for _name, _env in (
    ("langfuse_base_url", "LANGFUSE_BASE_URL"),
    ("langfuse_public_key", "LANGFUSE_PUBLIC_KEY"),
    ("langfuse_secret_key", "LANGFUSE_SECRET_KEY"),
):
    if not getattr(_obs, _name):
        setattr(_obs, _name, os.environ.get(_env, ""))

logger.info(f"配置加载完成 env={config.app_env}")
