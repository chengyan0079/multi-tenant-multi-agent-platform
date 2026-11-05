"""
protocol - 插件协议（设计文档 §8 / §15.2）

每个能力/工具实现统一 AgentPlugin 协议；BasePlugin 提供默认实现，具体插件继承并覆盖。
错误边界在 PluginRegistry 调用处统一捕获，单能力故障不影响整体。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol


@dataclass
class PluginManifest:
    """插件声明（manifest.yaml 解析后的结构）。"""

    name: str
    version: str
    capabilities: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    description: str = ""


class AgentPlugin(Protocol):
    """插件必须实现的能力面。"""

    @property
    def manifest(self) -> PluginManifest: ...

    def configure(self, config: Dict[str, Any]) -> None: ...

    async def register(self) -> None: ...

    def get_tools(self) -> List["BaseTool"]: ...

    async def health(self) -> bool: ...


class BaseTool(ABC):
    """一个可执行工具（如 rag_retrieve / web_search）。"""

    name: str = ""
    description: str = ""

    @abstractmethod
    async def run(self, **kwargs: Any) -> Any:
        """执行工具；超时/熔断由注册表包装。"""
        raise NotImplementedError


class BasePlugin(ABC):
    """插件基类，默认实现协议方法，子类填 manifest 与 get_tools。"""

    manifest: PluginManifest
    config: Dict[str, Any] = {}

    def configure(self, config: Dict[str, Any]) -> None:
        self.config = config

    async def register(self) -> None:
        return None

    @abstractmethod
    def get_tools(self) -> List[BaseTool]:
        raise NotImplementedError

    async def health(self) -> bool:
        return True
