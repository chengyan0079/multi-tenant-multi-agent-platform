"""统一会话服务：一次写入 turn / 短期记忆 / 长期记忆，统一读取上下文。"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from backend.app_state import app_state
from backend.common.logger import get_logger
from backend.orchestration.agent_spec import AgentSpec
from backend.orchestration.unified_schemas import LongTermMemoryBlock, ShortTermTurn

logger = get_logger("unified_conversation")


@dataclass
class ConversationContext:
    """load_context 装配结果（均为具体对象 / 列表，D17）。"""

    existing_summary: Optional[str]  # 会话级摘要
    short_term: list[ShortTermTurn]  # 短期窗口
    long_term: list[LongTermMemoryBlock]  # 长期记忆块


class UnifiedConversationService:
    """统一会话服务：turn / 短期记忆 / 长期记忆的唯一写入口。"""

    def __init__(
        self,
        *,
        turn_dao: Any = None,
        memory_store: Any = None,
        long_term_dao: Any = None,
        extractor: Any = None,
    ) -> None:
        from backend.data.dao.agent.unified_turn_dao import UnifiedTurnDao
        from backend.common.memory.memory import MemoryStore
        from backend.data.dao.business.long_term_memory_dao import LongTermMemoryDao
        from backend.services.long_term_memory_extractor import LongTermMemoryExtractor

        self.turn_dao = turn_dao or UnifiedTurnDao
        self.memory = memory_store or app_state.memory
        self.long_term_dao = long_term_dao or LongTermMemoryDao
        self.extractor = extractor or LongTermMemoryExtractor()

    async def append_turn(
        self,
        *,
        turn_id: str = "",
        thread_id: str,
        tenant_id: int,
        user_id: int,
        agent_type: str,
        spec_version: Optional[str],
        trace_id: Optional[str],
        turn_index: int,
        event_type: str,
        user_content: Optional[str] = None,
        assistant_content: Optional[str] = None,
        payload: Optional[dict[str, Any]] = None,
        routing: Optional[dict[str, Any]] = None,
        status: str = "success",
        error_code: Optional[str] = None,
        error_msg: Optional[str] = None,
        latency_ms: Optional[int] = None,
        token_usage: Optional[dict[str, Any]] = None,
    ) -> str:
        """写回一轮：turn 行 + 短期记忆 push。返回 turn_id。

        **落库失败直接抛异常**（不再降级吞掉）：turn 是会话历史唯一真相源，
        写失败若静默会导致轮次/记忆/回放全部缺失且难以察觉。
        """
        from backend.data.dao.agent.unified_turn_dao import UnifiedTurnRow

        row = UnifiedTurnRow(
            id=turn_id or str(uuid4()),
            tenant_id=tenant_id,
            user_id=user_id,
            thread_id=thread_id,
            trace_id=trace_id,
            turn_index=turn_index,
            agent_type=agent_type,
            spec_version=spec_version,
            event_type=event_type,
            user_content=user_content,
            assistant_content=assistant_content,
            payload=payload or {},
            routing=routing,
            status=status,
            error_code=error_code,
            error_msg=error_msg,
            latency_ms=latency_ms,
            token_usage=token_usage,
        )
        turn_id = await self.turn_dao.append(row=row)

        # 首轮自动命名（按咨询主题；仅当标题为空时写一次）
        if turn_index == 1 and user_content:
            from backend.data.dao.agent.thread_dao import ThreadDao

            title = " ".join((user_content or "").split())[:30] or "新会话"
            await ThreadDao.set_title_if_empty(
                thread_id=thread_id, tenant_id=tenant_id, title=title
            )

        # 短期记忆：每轮成功 / 停止 / 失败后 push
        try:
            if self.memory is not None:
                content = user_content or assistant_content or ""
                role = "user" if user_content else "assistant"
                await self.memory.push_short(
                    thread_id,
                    ShortTermTurn(
                        turn_id=str(turn_id),
                        role=role,
                        content=content,
                        agent_type=agent_type,
                        event_type=event_type,
                        create_at=datetime.now(timezone.utc),
                    ),
                )
        except Exception:
            logger.exception("短期记忆写入失败（降级，不影响主链路）")

        return str(turn_id)

    async def append_long_term(
        self,
        *,
        tenant_id: int,
        user_id: int,
        agent_id: str,
        summary: Optional[str] = None,
        turns: Optional[list[ShortTermTurn]] = None,
    ) -> None:
        """按阈值触发长期记忆抽取并写入 PG。

        写入失败直接抛出（不降级）：SQL 异常必须暴露，交由上层返回 code/msg。
        """
        blocks = await self.extractor.extract(
            agent_id=agent_id, summary=summary, turns=turns or []
        )
        for b in blocks:
            await self.long_term_dao.append(
                tenant_id=tenant_id,
                user_id=user_id,
                agent_id=b.agent_id or agent_id,
                block=b.block,
                content=b.content,
            )

    async def load_context(
        self,
        *,
        thread_id: str,
        tenant_id: int,
        user_id: int,
        spec: AgentSpec,
        existing_summary: Optional[str] = None,
    ) -> ConversationContext:
        """装配运行时上下文：会话内摘要 + 短期窗口 + 长期记忆（各自降级互不影响）。"""
        short_term: list[ShortTermTurn] = []
        long_term: list[LongTermMemoryBlock] = []

        if self.memory is not None:
            try:
                short_term = await self.memory.get_short(
                    thread_id, limit=spec.short_term_limit
                )
            except Exception:
                logger.exception("短期记忆读取失败（降级 short_term=[]）")
                short_term = []

        try:
            for block in spec.long_term_blocks:
                rows = await self.long_term_dao.list_recent(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    agent_id=spec.agent_type,
                    block=block,
                    limit=10,
                )
                long_term.extend(rows)
        except Exception:
            logger.exception("长期记忆读取失败（降级 long_term=[]）")
            long_term = []

        return ConversationContext(
            existing_summary=existing_summary,
            short_term=short_term,
            long_term=long_term,
        )
