"""config 包：AppSettings() 读 .env 校验 → config 单例。"""

from backend.config.settings import BASE_DIR, AppSettings, config

__all__ = ["AppSettings", "config", "BASE_DIR"]
