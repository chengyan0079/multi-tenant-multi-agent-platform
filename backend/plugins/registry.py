"""
registry - 运行时插件注册表（设计文档 §8 / §15.2）

持有所有已注册插件；按能力名查工具并带错误边界（单能力异常不扩散）。
与 AgentRegistry 联动：Agent 通过能力名取工具，不直接依赖具体插件实现。
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from backend.common.logger import get_logger
from backend.core.exception import CapabilityError
from backend.plugins.protocol import AgentPlugin, BaseTool

logger = get_logger("plugin_registry")


class PluginRegistry:
    """插件注册表：name -> plugin；capability -> tool 映射。"""

    def __init__(self) -> None:
        self._plugins: Dict[str, AgentPlugin] = {}
        self._tools: Dict[str, BaseTool] = {}

    async def start(self) -> None:
        for plugin in self._plugins.values():
            try:
                await plugin.register()
            except Exception as exc:
                logger.warning(f"插件注册失败(已跳过): {plugin.manifest.name} - {exc}")

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
            logger.warning(f"能力执行异常: {name} - {exc}")
            raise CapabilityError(f"能力失败: {name}", degradable=True, cause=exc)

    async def stop(self) -> None:
        self._plugins.clear()
        self._tools.clear()
