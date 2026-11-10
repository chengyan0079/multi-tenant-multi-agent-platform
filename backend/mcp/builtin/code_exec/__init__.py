"""code_exec 插件入口：导出 plugin 实例供 loader 发现。"""

from backend.mcp.builtin.code_exec.tool import CodeExecTool
from backend.mcp.protocol import BasePlugin, PluginManifest

manifest = PluginManifest(
    name="code_exec",
    version="0.1.0",
    capabilities=["code_exec"],
    description="代码题沙箱评估",
)


class CodeExecPlugin(BasePlugin):
    manifest = manifest

    def get_tools(self) -> list:
        return [CodeExecTool()]


plugin = CodeExecPlugin()
