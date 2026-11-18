"""plugins 包：能力缝隙。"""

from backend.tools.protocol import AgentPlugin, BaseTool, PluginManifest
from backend.tools.registry import PluginRegistry

__all__ = ["AgentPlugin", "BaseTool", "PluginManifest", "PluginRegistry"]
