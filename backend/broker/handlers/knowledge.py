"""知识库重索引 handler（低置信问答补充回流后向量化写 Milvus）。

本轮落鉴权与消息结构；向量化 + 写 Milvus 接 TODO，按 kpq_id 幂等（见文档 §6.3）。
"""
from __future__ import annotations

from backend.broker.envelope import TaskMessage
from backend.broker.security import authorize_task
from backend.common.logger import logger


async def handle_knowledge_reindex(msg: TaskMessage) -> None:
    # 知识库补充回流由 teacher / admin 触发（knowledge:upload）
    await authorize_task(msg.user_id, msg.tenant_id, ["knowledge:upload"])
    kpq_id = msg.payload.get("kpq_id")
    # TODO: 取补充内容 → 向量化 → 写 Milvus；按 kpq_id 幂等，避免重复索引
    logger.info(f"[knowledge.reindex] kpq_id={kpq_id} tenant={msg.tenant_id}")
