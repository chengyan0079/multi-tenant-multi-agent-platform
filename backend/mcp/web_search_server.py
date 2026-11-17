"""Web 搜索 MCP Server：包装 Tavily REST，供本进程经 MCP 协议调用。"""
from __future__ import annotations

import os
from typing import Any

import httpx
from fastmcp import FastMCP

from backend.common.logger import get_logger

logger = get_logger("mcp.web_search_server")

web_search_mcp = FastMCP(name="Web-Search-Tool")
_TAVILY_ENDPOINT = "https://api.tavily.com/search"
_TIMEOUT_S = 15.0


@web_search_mcp.tool(description="Web 搜索工具")
async def web_search(query: str, max_results: int) -> list[dict[str, Any]]:
    """按关键词检索互联网，返回标题、链接与摘要。"""
    api_key = os.environ.get("TAVILY_API_KEY", "")
    if not query.strip() or not api_key:
        return []

    async with httpx.AsyncClient(timeout=_TIMEOUT_S) as client:
        resp = await client.post(
            _TAVILY_ENDPOINT,
            json={
                "api_key": api_key,
                "query": query,
                "max_results": max_results,
                "include_answer": False,
                "include_raw_content": False,
            },
        )
        resp.raise_for_status()

    results = [
        {
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "snippet": r.get("content", "")[:512],
        }
        for r in resp.json().get("results", [])
    ]
    logger.info(f"web_search_mcp.tavily_done | hits={len(results)}")
    return results
