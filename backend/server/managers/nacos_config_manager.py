"""NacosConfigManager（order 105）：配置中心启动（对齐 RAG-Ultra）。

与 NacosDiscoverManager（仅服务发现）独立。本启动项：
  1. 拉起 ConfigCenterLoader（SDK gRPC 长连接订阅变更），注入 app_state 供健康检查读取；
  2. 把 PROMPT 组提示词配置拉取并写入 Redis 预热（core.config_center.prompts_cache）。
两者都是旁路能力：失败只告警，不阻断启动（运行时取配置会直连 Nacos 兜底）。
"""
from __future__ import annotations

import asyncio

from backend.app_state import app_state
from backend.common.logger import logger
from backend.config import config as app_config
from backend.core.config_center.loader import get_config_center_loader
from backend.core.config_center.prompts_cache import warmup_prompts
from backend.server.base_manager import BaseManager


class NacosConfigManager(BaseManager):
    async def start(self) -> None:
        loader = get_config_center_loader()
        app_state.config_center = loader
        try:
            await loader.start()
        except Exception as e:  # 配置中心不阻断启动
            logger.warning(f"配置中心热加载启动失败，运行时将直连 Nacos 兜底: {e}")

        if not app_config.nacos_config.enabled:
            logger.info("配置中心未启用（NACOS_CONFIG_ENABLED=False），跳过提示词预热")
            return
        try:
            await asyncio.to_thread(warmup_prompts)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"提示词预热失败，运行时将直连 Nacos 兜底: {e}")

    async def stop(self) -> None:
        try:
            await get_config_center_loader().stop()
        except Exception as e:
            logger.warning(f"配置中心热加载停止异常: {e}")
        app_state.config_center = None
