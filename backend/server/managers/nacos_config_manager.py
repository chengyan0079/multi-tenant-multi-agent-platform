"""NacosConfigManager（order 105）：拉起配置中心订阅 + 提示词预热写入 Redis；失败只告警不阻断。"""

from __future__ import annotations

from backend.app_state import app_state
from backend.common.config_center.prompts_cache import warmup_prompts
from backend.common.logger import logger
from backend.config import config as app_config
from backend.data.clients.nacos import NacosClient
from backend.server.base_manager import BaseManager, HealthInfo


class NacosConfigManager(BaseManager):
    async def start(self) -> None:
        client = app_state.clients.ensure(
            "nacos", lambda: NacosClient.from_settings(app_config.nacos)
        )
        loader = client.loader
        app_state.config_center = loader
        # 配置中心启动失败即视为启动失败（fail-fast），交由 AppServer 终止启动
        await loader.start()

        if not app_config.nacos_config.enabled:
            logger.warning("配置中心未启用（NACOS_CONFIG_ENABLED=False），跳过提示词预热")
            return
        # 提示词预热失败同样 fail-fast（不再静默兜底）
        await warmup_prompts()

    async def stop(self) -> None:
        if app_state.clients.has("nacos"):
            try:
                await app_state.clients.get_as("nacos", NacosClient).loader.stop()
            except Exception as e:
                logger.exception(f"配置中心热加载停止异常: {e}")
        app_state.config_center = None

    async def health(self) -> HealthInfo:
        if not app_config.nacos_config.enabled:
            return HealthInfo(status="running", detail="配置中心未启用，跳过")
        if app_state.config_center is None:
            return HealthInfo(status="degraded", detail="配置中心未就绪（运行时直连兜底）")
        return HealthInfo(status="running")
