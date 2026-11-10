"""code_exec 工具：代码题沙箱评估（规划中）。"""

from __future__ import annotations

from typing import Any

from backend.mcp.protocol import BaseTool


class CodeExecTool(BaseTool):
    name = "code_exec"
    description = "在受控沙箱执行代码片段并返回结果/错误"

    async def run(self, **kwargs: Any) -> dict:
        # 占位实现：真实接沙箱运行时（规划中），失败由注册表降级
        return {"stdout": "", "stderr": "未实现", "exit_code": -1}
