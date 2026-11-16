"""长期记忆写入钩子：各 agent 在关键节点复用（失败降级，不影响主链路）。

- qa：每 N 轮摘要压缩后写
- db_review：审批通过后写（记住评审偏好）
- db_release：放行/拒绝后写（记住沙箱偏好）
"""

from __future__ import annotations

from typing import Any

from backend.common.logger import logger


async def persist_long_term(
    *, agent_id: str, state: Any, summary: str | None = None
) -> None:
    """把摘要/关键结论抽取为长期记忆块写入 agent_long_term_memory。"""
    text = summary
    if not text and hasattr(state, "get"):
        text = state.get("existing_summary") or state.get("memory_summary")
    if not text:
        return
    tenant_id = int((state.get("tenant_id") if hasattr(state, "get") else 0) or 0)
    user_id = int((state.get("user_id") if hasattr(state, "get") else 0) or 0)
    if not tenant_id or not user_id:
        return
    try:
        from backend.services.unified_conversation import UnifiedConversationService

        await UnifiedConversationService().append_long_term(
            tenant_id=tenant_id,
            user_id=user_id,
            agent_id=agent_id,
            summary=text,
        )
        logger.debug(f"long_term.persisted | agent={agent_id} tenant={tenant_id}")
    except Exception:  # noqa: BLE001 - SQL 异常必须暴露，不降级
        raise
