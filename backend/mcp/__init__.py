"""plugins 包：能力缝隙。"""

from backend.mcp.protocol import AgentPlugin, BaseTool, PluginManifest
from backend.mcp.registry import PluginRegistry

__all__ = ["AgentPlugin", "BaseTool", "PluginManifest", "PluginRegistry"]
