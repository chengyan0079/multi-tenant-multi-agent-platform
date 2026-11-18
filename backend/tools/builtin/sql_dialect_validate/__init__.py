"""sql_dialect_validate 插件入口：导出 plugin 实例供 loader 发现。"""

from backend.tools.builtin.sql_dialect_validate.tool import SqlDialectValidateTool
from backend.tools.protocol import BasePlugin, PluginManifest

manifest = PluginManifest(
    name="sql_dialect_validate",
    version="0.1.0",
    capabilities=["sql_validate"],
    description="SQL 方言校验",
)


class SqlDialectValidatePlugin(BasePlugin):
    manifest = manifest

    def get_tools(self) -> list:
        return [SqlDialectValidateTool()]


plugin = SqlDialectValidatePlugin()
