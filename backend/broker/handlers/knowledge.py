"""知识库重索引 handler（低置信问答补充回流后向量化写 Milvus）。

handler 只做鉴权与消息结构，回流索引见 services/indexing.py。
"""
from __future__ import annotations

from backend.broker.envelope import TaskMessage
from backend.broker.security import authorize_task
from backend.services.indexing import reindex_knowledge


async def handle_knowledge_reindex(msg: TaskMessage) -> None:
    # 知识库补充回流由 teacher / admin 触发（knowledge:upload）
    await authorize_task(msg.header.user_id, msg.header.tenant_id, ["knowledge:upload"])
    await reindex_knowledge(
        kpq_id=msg.data.get("kpq_id"),
        tenant_id=msg.header.tenant_id,
    )
