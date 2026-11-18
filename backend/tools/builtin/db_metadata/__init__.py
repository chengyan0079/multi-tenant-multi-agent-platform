"""db_metadata 插件入口：导出 plugin 实例供 loader 发现。"""

from backend.tools.builtin.db_metadata.tool import DbMetadataTool
from backend.tools.protocol import BasePlugin, PluginManifest

manifest = PluginManifest(
    name="db_metadata",
    version="0.1.0",
    capabilities=["db_metadata"],
    description="目标库元数据读取（只读）",
)


class DbMetadataPlugin(BasePlugin):
    manifest = manifest

    def get_tools(self) -> list:
        return [DbMetadataTool()]


plugin = DbMetadataPlugin()
