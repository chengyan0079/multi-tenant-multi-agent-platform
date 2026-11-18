"""运行时插件注册表：name→plugin、capability→tool 映射，单能力异常不扩散。"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from backend.common.logger import get_logger
from backend.observability.exception import CapabilityError
from backend.tools.protocol import AgentPlugin, BaseTool

logger = get_logger("plugin_registry")


class PluginRegistry:
    """插件注册表：name -> plugin；capability -> tool 映射。"""

    def __init__(self) -> None:
        self._plugins: Dict[str, AgentPlugin] = {}
        self._tools: Dict[str, BaseTool] = {}
        # 租户 → 已注册（启用）的工具名集合；按 agent_tool 租户 enabled 注册
        self._tenant_tools: Dict[int, set] = {}

    def set_tenant_tools(self, mapping: Dict[int, set]) -> None:
        self._tenant_tools = mapping

    def tenant_tool_names(self, tenant_id: int) -> list:
        return sorted(self._tenant_tools.get(tenant_id, set()))

    def is_tool_enabled_for_tenant(self, tenant_id: int, name: str) -> bool:
        if not self._tenant_tools:
            # 未按租户加载（离线/测试）：不限制
            return True
        return name in self._tenant_tools.get(tenant_id, set())

    async def start(self) -> None:
        for plugin in self._plugins.values():
            try:
                await plugin.register()
            except Exception as exc:
                logger.exception(f"插件注册失败(已跳过): {plugin.manifest.name} - {exc}")

    def register_plugin(self, plugin: AgentPlugin) -> None:
        """注册一个插件并把它的工具按 name 编入能力表。"""
        self._plugins[plugin.manifest.name] = plugin
        for tool in plugin.get_tools():
            if tool.name in self._tools and tool.name:
                logger.warning(f"工具名冲突，覆盖: {tool.name}")
            self._tools[tool.name] = tool
        logger.info(f"插件注册: {plugin.manifest.name} caps={plugin.manifest.capabilities}")

    def get_tool(self, name: str) -> Optional[BaseTool]:
        return self._tools.get(name)

    def list_capabilities(self) -> List[str]:
        return sorted(self._tools.keys())

    @property
    def plugin_count(self) -> int:
        """已注册插件数量（用于启动期就绪自检判定 registry 是否非空）。"""
        return len(self._plugins)

    async def call(self, name: str, timeout_s: float = 10.0, **kwargs: Any) -> Any:
        """调用能力工具（带超时错误边界）。degradable 异常上抛 CapabilityError 供编排降级。"""
        tool = self._tools.get(name)
        if tool is None:
            raise CapabilityError(f"未知能力: {name}", degradable=True)
        try:
            return await asyncio.wait_for(tool.run(**kwargs), timeout=timeout_s)
        except asyncio.TimeoutError as exc:
            raise CapabilityError(f"能力超时: {name}", degradable=True, cause=exc)
        except Exception as exc:
            logger.exception(f"能力执行异常: {name} - {exc}")
            raise CapabilityError(f"能力失败: {name}", degradable=True, cause=exc)

    async def stop(self) -> None:
        self._plugins.clear()
        self._tools.clear()
