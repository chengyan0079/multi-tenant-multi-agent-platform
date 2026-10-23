"""plugins 包：能力缝隙。"""
from backend.plugins.protocol import AgentPlugin, BaseTool, PluginManifest
from backend.plugins.registry import PluginRegistry

__all__ = ["AgentPlugin", "BaseTool", "PluginManifest", "PluginRegistry"]
