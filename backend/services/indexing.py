"""索引类业务的实现入口：文档解析与知识库回流。

两条链路的共同终点是 Milvus（dense + sparse 双向量），差别在数据来源：
- 文档解析：MinIO 文件 → 解析 → 分块；
- 知识回流：知识补充队列里的问答对 → 拼装文本。
"""
from __future__ import annotations

from backend.common.logger import logger
from backend.data.dao.business.file_dao import FileDao


async def parse_document(
    *,
    file_id: int | None,
    object_key: str | None,
    bucket: str | None,
    file_ext: str | None,
    tenant_id: int | None,
) -> None:
    """解析上传文件并写入向量库。

    TODO(doc.parse)：
    1. storage.get_bytes(object_key) 取文件；
    2. 按扩展名解析：.pdf → pymupdf 提取文本与版面，.md → 直接读文本；
    3. 智能分块（标题感知 / 递归字符）；
    4. LLMFactory.embed 向量化：dense(1024, IP) + sparse(倒排, IP)；
    5. DocumentMilvusStore.add_chunks(...) 写入 Milvus（tenant_id 作分区键）；
    6. FileDao.set_parse_status([file_id], "parsed", tenant_id=tenant_id)。
    解析过程中的异常向上抛，由消费端重试；重试超限后由定时任务兜底标 failed。
    """
    logger.warning(
        f"[doc.parse] 解析链路未接入 file_id={file_id} key={object_key} "
        f"bucket={bucket} ext={file_ext} tenant={tenant_id}，回写 failed"
    )
    # 入队前状态已置 parsing，这里不回写会让文件永远停在"解析中"
    if file_id is not None:
        await FileDao.set_parse_status([file_id], "failed", tenant_id=tenant_id)


async def reindex_knowledge(*, kpq_id: int | None, tenant_id: int | None) -> None:
    """把知识补充内容回流索引。

    TODO(knowledge.reindex)：
    1. KnowledgePendingQueueDao 按 kpq_id 取出补充内容（已由人工确认）；
    2. 拼装成可索引文本（问题 + 答案 + 来源）；
    3. LLMFactory.embed 向量化（dense + sparse）；
    4. DocumentMilvusStore.add_chunks(...) 写入，按 kpq_id 幂等（重复索引前先删除同源块）；
    5. 回写队列状态为 processed，避免被重复消费。
    """
    logger.warning(
        f"[knowledge.reindex] 回流索引未接入 kpq_id={kpq_id} tenant={tenant_id}"
    )
