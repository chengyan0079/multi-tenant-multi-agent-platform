"""
client - 接入 RAG-Ultra（设计文档 §6.2 / §12）

两种接入方式：① 包导入（import_path 指向 RAG-Ultra 工程目录，复用其检索/索引能力）；
② HTTP（http_base 指向已部署的 rag-ultra 服务）。优先包导入，无则降级 HTTP。
禁止把检索代码复制进本仓库（双份维护风险）。
"""
from __future__ import annotations

import sys
from typing import Any, Dict, List, Optional

from backend.app_state import app_state
from backend.common.logger import get_logger
from backend.observability.exception import CapabilityError

logger = get_logger("rag_client")


class RagUltraClient:
    """rag-ultra 接入客户端；首次调用惰性建立连接。"""

    def __init__(self) -> None:
        self._module = None
        self._http = None

    def _ensure(self) -> None:
        if self._module is not None or self._http is not None:
            return
        cfg = app_state.settings.rag_ultra
        if cfg.import_path:
            try:
                if cfg.import_path not in sys.path:
                    sys.path.insert(0, cfg.import_path)
                # 复用 RAG-Ultra 的检索入口（具体路径按其工程接口调整）
                self._module = __import__("core.rag_retriever.retriever", fromlist=["RagRetriever"])
                logger.info("rag-ultra 包导入成功")
                return
            except Exception as exc:
                logger.warning(f"rag-ultra 包导入失败，尝试 HTTP: {exc}")
        if cfg.http_base:
            import httpx

            self._http = httpx.AsyncClient(base_url=cfg.http_base, timeout=30.0)
            logger.info(f"rag-ultra HTTP 客户端: {cfg.http_base}")
            return
        raise CapabilityError("rag-ultra 未配置（import_path/http_base）", degradable=True)

    async def retrieve(self, query: str, tenant_id: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """调用 rag-ultra 混合召回 + bge-reranker 精排，返回命中块列表。"""
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


client = RagUltraClient()
