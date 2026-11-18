"""slow_sql_explain 插件入口：导出 plugin 实例供 loader 发现。"""

from backend.tools.builtin.slow_sql_explain.tool import SlowSqlExplainTool
from backend.tools.protocol import BasePlugin, PluginManifest

manifest = PluginManifest(
    name="slow_sql_explain",
    version="0.1.0",
    capabilities=["slow_sql"],
    description="慢 SQL 纯分析（不连库）",
)


class SlowSqlExplainPlugin(BasePlugin):
    manifest = manifest

    def get_tools(self) -> list:
        return [SlowSqlExplainTool()]


plugin = SlowSqlExplainPlugin()
