"""web_search 插件入口：导出 plugin 实例供 loader 发现。"""
from backend.plugins.builtin.web_search.tool import WebSearchTool
from backend.plugins.protocol import BasePlugin, PluginManifest

manifest = PluginManifest(
    name="web_search",
    version="0.1.0",
    capabilities=["web_search"],
    description="联网兜底检索",
)


class WebSearchPlugin(BasePlugin):
    manifest = manifest

    def get_tools(self) -> list:
        return [WebSearchTool()]


plugin = WebSearchPlugin()
