"""索引类业务入口：委托 rag 完成文档解析与知识库回流，终点为 Milvus 双向量。"""

from __future__ import annotations

from backend.common.logger import logger
from backend.rag.indexing import index_document, mark_parse_failed


async def parse_document(
    *,
    file_id: int | None,
    object_key: str | None,
    bucket: str | None,
    file_ext: str | None,
    tenant_id: int | None,
    file_name: str | None = None,
) -> None:
    """解析上传文件并写入向量库（qa.parse 消息 handler 调用）。

    成功由 backend/rag/indexing 回写 parsed；失败回写 failed 并把异常上抛，
    由消费端重试，重试超限后落死信表。
    """
    try:
        written = await index_document(
            file_id=file_id,
            object_key=object_key or "",
            file_ext=file_ext,
            tenant_id=tenant_id,
            file_name=file_name,
        )
        logger.info(
            f"[qa.parse] 解析完成 file_id={file_id} key={object_key} "
            f"bucket={bucket} ext={file_ext} tenant={tenant_id} chunks={written}"
        )
    except Exception as exc:
        await mark_parse_failed(file_id, tenant_id)
        logger.exception(f"[qa.parse] 解析失败 file_id={file_id}：{exc}")
        raise
