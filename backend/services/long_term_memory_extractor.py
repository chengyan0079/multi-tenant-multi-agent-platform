"""长期记忆抽取：从会话摘要 / 短期窗口抽取 summary/fact/preference 块（§5.8）。

抽取失败只由调用方降级（不中断主链路、不改变轮次状态）。真实实现应调用 LLM
（LONG_MEMORY_EXTRACT_PROMPT）；本期默认实现为确定性占位，测试可注入 extract_fn。
"""
from __future__ import annotations

import inspect
from typing import Awaitable, Callable, Optional

from backend.orchestration.unified_schemas import LongTermMemoryBlock, ShortTermTurn


class LongTermMemoryExtractor:
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
        result = self._extract_fn(agent_id=agent_id, summary=summary, turns=turns)
        if inspect.isawaitable(result):
            result = await result
        return result

    @staticmethod
    async def _default_extract(
        *, agent_id: str, summary: Optional[str], turns: list[ShortTermTurn]
    ) -> list[LongTermMemoryBlock]:
        # 一期 PoC：仅当提供 summary 时产出一个 summary 块（真实实现替换为 LLM 抽取）
        if summary:
            return [LongTermMemoryBlock(agent_id=agent_id, block="summary", content=summary)]
        return []
