"""文档解析入库 pipeline：MinIO 字节 → 加载 → 分块 → 向量化写 Milvus → 回写状态，按 file_id 幂等 upsert。"""

from __future__ import annotations

from typing import Any

from backend.app_state import app_state
from backend.common.logger import logger
from backend.config import config
from backend.data.clients.minio import get_object_bytes
from backend.data.dao.business.file_dao import FileDao
from backend.rag.loaders import load_document
from backend.rag.ranked import TextChunk
from backend.rag.splitters import split_documents


def _chunks_to_rows(
    chunks: list[TextChunk],
    *,
    file_id: Any,
    file_name: str,
    tenant_id: int | None,
) -> list[dict[str, Any]]:
    """把父子子片转成 DocumentMilvusStore.add_chunks 期望的行结构（全部显式字段）。"""
    rows: list[dict[str, Any]] = []
    for chunk in chunks:
        meta = chunk.metadata
        extra = dict(meta.get("extra") or {})
        extra.setdefault("doc_type", meta.get("doc_type", ""))
        extra.setdefault("file_hash", meta.get("file_hash", ""))
        rows.append(
            {
                "text": chunk.text,
                "tenant_id": str(tenant_id or 0),
                "file_id": str(file_id),
                "file_name": file_name,
                "parent_id": meta.get("parent_id", ""),
                "parent_content": meta.get("parent_content", chunk.text),
                "chunk_type": meta.get("chunk_type", "child"),
                "chunk_index": int(meta.get("chunk_index", 0)),
                "child_index": int(meta.get("child_index", 0)),
                "page": int(meta.get("page", 0) or 0),
                "source_location": meta.get("source_location") or file_name,
                "extra": extra,
            }
        )
    return rows


async def delete_file_chunks(*, file_id: Any, tenant_id: int | None) -> None:
    """删除某文件的旧向量块（重新解析前调用，保证幂等）。"""
    store = app_state.milvus_store
    if store is None or store.client is None:
        raise RuntimeError("Milvus 存储未就绪")
    await store.delete_by_file_id(file_id)
    logger.debug(f"rag.index: 已清理旧块 file_id={file_id}")


async def index_document(
    *,
    file_id: Any,
    object_key: str,
    file_ext: str | None,
    tenant_id: int | None,
    file_name: str | None = None,
) -> int:
    """解析单个文件并写入向量库，返回写入块数。

    失败时异常上抛，由调用方回写 parse_status=failed 并让 broker 重试。
    """
    store = app_state.milvus_store
    if store is None or store.client is None:
        raise RuntimeError("Milvus 存储未就绪")
    if not object_key:
        raise ValueError("object_key 缺失，无法取文件")

    data = await get_object_bytes(object_key)
    name = file_name or object_key.rsplit("/", 1)[-1]
    pages = load_document(data, file_name=name, file_ext=file_ext)
    if not pages:
        raise ValueError(f"文档无有效文本内容 file={name}")

    chunks = split_documents(pages, file_ext=file_ext or "", file_id=str(file_id))
    if not chunks:
        raise ValueError(f"文档分块结果为空 file={name}")

    rows = _chunks_to_rows(chunks, file_id=file_id, file_name=name, tenant_id=tenant_id)
    await delete_file_chunks(file_id=file_id, tenant_id=tenant_id)
    written = await store.add_chunks(rows, batch_size=config.qa.index_batch_size)
    if file_id is not None:
        await FileDao.set_parse_status([int(file_id)], "parsed", tenant_id=tenant_id)
    logger.info(
        f"rag.index.done | file_id={file_id} file={name} pages={len(pages)} "
        f"chunks={written} tenant={tenant_id}"
    )
    return written


async def mark_parse_failed(file_id: Any, tenant_id: int | None) -> None:
    """解析失败时回写状态，避免文件永远卡在 parsing。"""
    if file_id is None:
        return
    try:
        await FileDao.set_parse_status([int(file_id)], "failed", tenant_id=tenant_id)
    except Exception as exc:  # noqa: BLE001 - 状态回写失败不掩盖原始解析异常
        logger.exception(f"rag.index: 回写 failed 状态失败 file_id={file_id}：{exc}")
