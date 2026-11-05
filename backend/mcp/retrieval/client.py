"""
client - 接入 RAG 检索（设计文档 §6.2 / §12）

三种接入方式：① MCP 服务（mcp_url 指向对外暴露的 MCP 服务，优先）；
② 包导入（import_path 指向检索工程目录，参考其检索/索引能力实现）；
③ HTTP（http_base 指向已部署的检索服务）。优先 MCP，无则降级到包导入 / HTTP。
禁止把检索代码复制进本仓库（双份维护风险）。
"""
from __future__ import annotations

import sys
from typing import Any, Dict, List, Optional

from backend.app_state import app_state
from backend.common.logger import get_logger
from backend.observability.exception import CapabilityError

logger = get_logger("rag_client")


class RagClient:
    """RAG 接入客户端；首次调用惰性建立连接。"""

    def __init__(self) -> None:
        self._module = None
        self._http = None

    def _ensure(self) -> None:
        if self._module is not None or self._http is not None:
            return
        cfg = app_state.settings.rag
        if cfg.import_path:
            try:
                if cfg.import_path not in sys.path:
                    sys.path.insert(0, cfg.import_path)
                # 参考检索工程的检索入口（具体路径按其接口调整）
                self._module = __import__("core.rag_retriever.retriever", fromlist=["RagRetriever"])
                logger.info("RAG 包导入成功")
                return
            except Exception as exc:
                logger.warning(f"RAG 包导入失败，尝试 HTTP: {exc}")
        if cfg.http_base:
            import httpx

            self._http = httpx.AsyncClient(base_url=cfg.http_base, timeout=30.0)
            logger.info(f"RAG HTTP 客户端: {cfg.http_base}")
            return
        raise CapabilityError("RAG 未配置（import_path/http_base）", degradable=True)

    async def retrieve(self, query: str, tenant_id: int, top_k: int = 5) -> List[Dict[str, Any]]:
        """调用 RAG 混合召回 + bge-reranker 精排，返回命中块列表。

        接入优先级：MCP 服务（RAG_MCP_URL）> 包导入（RAG_IMPORT_PATH）> HTTP（RAG_HTTP_BASE）。
        MCP 模式经对外暴露的 MCP 工具调用检索接口，无需在仓库内复制检索代码。
        """
        cfg = app_state.settings.rag
        if cfg.mcp_url:
            from backend.mcp.retrieval.mcp_client import mcp_retrieve

            return await mcp_retrieve(query, tenant_id, top_k)
        self._ensure()
        if self._module is not None:
            retriever = self._module.RagRetriever
            return await retriever.asearch(query=query, tenant_id=tenant_id, top_k=top_k)
        resp = await self._http.post(
            "/v1/retrieve",
            json={"query": query, "tenant_id": tenant_id, "top_k": top_k},
        )
        resp.raise_for_status()
        return resp.json().get("data", [])

    async def stop(self) -> None:
        if self._http is not None:
            await self._http.aclose()
        self._http = self._module = None


client = RagClient()
