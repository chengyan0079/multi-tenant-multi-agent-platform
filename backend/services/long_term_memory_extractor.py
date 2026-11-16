"""长期记忆抽取：从会话摘要 / 短期窗口抽取 summary/fact/preference 块。

默认实现调用 LLM（LONG_MEMORY_EXTRACT_PROMPT）做结构化抽取；抽取失败仅记日志并降级为
summary 块，不影响主链路。测试可注入 extract_fn 替换实现。
"""
from __future__ import annotations

import inspect
import json
from typing import Awaitable, Callable, Optional

from backend.common.logger import logger
from backend.common.llm.llm_factory import get_llm
from backend.orchestration.unified_schemas import LongTermMemoryBlock, ShortTermTurn
from backend.prompts.unified import LONG_MEMORY_EXTRACT_PROMPT


class LongTermMemoryExtractor:
    """长期记忆抽取器：默认 LLM 抽取，可注入 extract_fn 替换。"""

    def __init__(
        self,
        *,
        extract_fn: Optional[Callable[..., Awaitable[list[LongTermMemoryBlock]]]] = None,
    ) -> None:
        self._extract_fn = extract_fn or self._default_extract

    async def extract(
        self,
        *,
        agent_id: str,
        summary: Optional[str],
        turns: list[ShortTermTurn],
    ) -> list[LongTermMemoryBlock]:
        """抽取长期记忆块（summary / fact / preference）。"""
        result = self._extract_fn(agent_id=agent_id, summary=summary, turns=turns)
        if inspect.isawaitable(result):
            result = await result
        return result

    @staticmethod
    def _parse_blocks(text: str) -> list[dict]:
        """从 LLM 响应解析 [{block, content}]；容错：去掉代码块标记、截取首个 JSON 数组。"""
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```", 2)[1]
            if cleaned and cleaned[0].isalpha() and ":" not in cleaned[0:5]:
                cleaned = cleaned.split("\n", 1)[-1]  # 去掉 ```json 之类语言标记
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            start = cleaned.find("[")
            end = cleaned.rfind("]")
            if start == -1 or end == -1:
                return []
            try:
                data = json.loads(cleaned[start : end + 1])
            except json.JSONDecodeError:
                return []
        if not isinstance(data, list):
            return []
        out: list[dict] = []
        for item in data:
            if isinstance(item, dict) and item.get("block") and item.get("content"):
                out.append({"block": str(item["block"]), "content": str(item["content"])})
        return out

    @staticmethod
    async def _default_extract(
        *, agent_id: str, summary: Optional[str], turns: list[ShortTermTurn]
    ) -> list[LongTermMemoryBlock]:
        """默认实现：调用 LLM 从摘要抽取长期记忆块；失败降级为 summary 块。"""
        if not summary:
            return []
        try:
            llm = await get_llm(agent_id)
            resp = await llm.ainvoke(LONG_MEMORY_EXTRACT_PROMPT.format(summary=summary))
            content = resp.content if hasattr(resp, "content") else str(resp)
            parsed = LongTermMemoryExtractor._parse_blocks(content)
            blocks = [
                LongTermMemoryBlock(agent_id=agent_id, block=b["block"], content=b["content"])
                for b in parsed
            ]
            if blocks:
                return blocks
        except Exception as e:  # noqa: BLE001 - 抽取失败不影响主链路
            logger.warning("long_term_memory.extract_failed", agent_id=agent_id, error=str(e))
        return [LongTermMemoryBlock(agent_id=agent_id, block="summary", content=summary)]
