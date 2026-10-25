"""
settings - 配置单例：AppSettings() 直接读 .env 校验，导出 config。

加载与校验由 pydantic-settings 负责（env_file + 环境变量覆盖、fail-fast），
其余模块只消费本模块的 config，不直接读 env。
"""
from __future__ import annotations

from pathlib import Path

from backend.common.logger import get_logger
from backend.config.schemas import AppSettings

logger = get_logger("config")

# 项目根目录：config/settings.py 位于 <ROOT>/backend/config，向上 2 级到项目根
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# 模块级单例：导入即加载并校验（校验失败直接抛错 fail-fast）
config: AppSettings = AppSettings()
logger.info(f"配置加载完成 env={config.app_env}")
