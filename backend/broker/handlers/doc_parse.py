"""文档解析 handler：消费 doc.parse 消息，交给索引服务处理。

handler 只做鉴权与消息结构，解析 / 分块 / 向量化见 services/indexing.py。
"""
from __future__ import annotations

from backend.broker.envelope import TaskMessage
from backend.broker.security import authorize_task
from backend.services.indexing import parse_document


async def handle_doc_parse(msg: TaskMessage) -> None:
    # 解析链路走 file:upload 权限点（与上传同源），零信任重新校验
    await authorize_task(msg.header.user_id, msg.header.tenant_id, ["file:upload"])
    await parse_document(
        file_id=msg.data.get("file_id"),
        object_key=msg.data.get("object_key"),
        bucket=msg.data.get("bucket"),
        file_ext=msg.data.get("file_ext"),
        tenant_id=msg.header.tenant_id,
    )
