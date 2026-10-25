"""web_search 工具：低置信问答的联网兜底。"""
from __future__ import annotations

from typing import Any, List

from backend.mcp.protocol import BaseTool


class WebSearchTool(BaseTool):
    name = "web_search"
    description = "联网检索结果兜底，输入 query 返回片段列表"

    async def run(self, **kwargs: Any) -> List[dict]:
        query = kwargs.get("query", "")
        # 占位实现：真实接入搜索引擎 API（规划中）。失败时由注册表降级不阻断主链路。
        return [{"source": "web", "query": query, "snippet": ""}]
