"""qa 知识库文档解析 handler：消费 qa.parse 消息，交给索引服务处理。

handler 只做鉴权与消息结构，解析 / 分块 / 向量化见 services/indexing.py。
"""

from __future__ import annotations

from backend.broker.envelope import TaskMessage
from backend.broker.security import authorize_task
from backend.observability.exception import BizException
from backend.rag.indexing import mark_parse_failed
from backend.security.rbac import Scope
from backend.services.indexing import parse_document


async def handle_qa_parse(msg: TaskMessage) -> None:
    # 解析链路走 file:upload 权限点（与上传同源），零信任重新校验
    try:
        await authorize_task(msg.header.user_id, msg.header.tenant_id, [Scope.QA_FILE_UPLOAD])
    except BizException:
        # 鉴权失败不会进入 parse_document 的失败回写，这里补上，避免文件永远停在 parsing
        await mark_parse_failed(msg.data.get("file_id"), msg.header.tenant_id)
        raise
    await parse_document(
        file_id=msg.data.get("file_id"),
        object_key=msg.data.get("object_key"),
        bucket=msg.data.get("bucket"),
        file_ext=msg.data.get("file_ext"),
        file_name=msg.data.get("file_name"),
        tenant_id=msg.header.tenant_id,
    )
