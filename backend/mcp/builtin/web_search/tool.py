"""web_search 工具：低置信问答的联网兜底，接 Tavily 搜索 API。"""
from __future__ import annotations

import os
from typing import Any, List

import httpx

from backend.common.logger import logger
from backend.data.dao.agent.tool_dao import get_tool_config
from backend.mcp.protocol import BaseTool

_TAVILY_ENDPOINT = "https://api.tavily.com/search"
_TIMEOUT_S = 15.0


class WebSearchTool(BaseTool):
    """联网检索兜底工具：未配置 api_key 或调用失败时返回降级占位，不抛异常。"""

    name = "web_search"
    description = "联网检索结果兜底，输入 query 返回片段列表"

    async def run(self, **kwargs: Any) -> List[dict]:
        query = (kwargs.get("query") or "").strip()
        if not query:
            return []
        cfg = await get_tool_config("web_search")
        # 配置优先级：agent_tool.config.api_key > 环境变量 TAVILY_API_KEY
        api_key = cfg.get("api_key") or os.environ.get("TAVILY_API_KEY")
        if not api_key:
            return [{"source": "web", "query": query, "snippet": "", "degraded": True}]
        try:
            return await self._tavily(query, api_key, cfg)
        except Exception as exc:  # noqa: BLE001 - 搜索失败降级，不阻断主链路
            logger.warning("web_search.failed", query=query, error=str(exc))
            return [{"source": "web", "query": query, "snippet": "", "degraded": True}]

    @staticmethod
    async def _tavily(query: str, api_key: str, cfg: dict) -> List[dict]:
        endpoint = cfg.get("endpoint") or _TAVILY_ENDPOINT
        payload = {
            "api_key": api_key,
            "query": query,
            "max_results": int(cfg.get("max_results", 5)),
            "include_answer": False,
            "include_raw_content": False,
        }
        async with httpx.AsyncClient(timeout=_TIMEOUT_S) as client:
            resp = await client.post(endpoint, json=payload)
            resp.raise_for_status()
            data = resp.json()
        results = [
            {
                "source": r.get("url", "web"),
                "query": query,
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "snippet": r.get("content", ""),
            }
            for r in data.get("results", [])
        ]
        if not results:
            return [{"source": "web", "query": query, "snippet": "", "degraded": True}]
        return results
