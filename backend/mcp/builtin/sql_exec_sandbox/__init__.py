"""sql_exec_sandbox 插件入口：导出 plugin 实例供 loader 发现。"""

from backend.mcp.builtin.sql_exec_sandbox.tool import SqlExecSandboxTool
from backend.mcp.protocol import BasePlugin, PluginManifest

manifest = PluginManifest(
    name="sql_exec_sandbox",
    version="0.1.0",
    capabilities=["sql_exec_sandbox"],
    description="沙箱执行已审批 SQL（env=sandbox，无外部 SQL 入参）",
)


class SqlExecSandboxPlugin(BasePlugin):
    manifest = manifest

    def get_tools(self) -> list:
        return [SqlExecSandboxTool()]


plugin = SqlExecSandboxPlugin()
