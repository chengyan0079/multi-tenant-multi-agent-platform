"""drop_rag_collection - 删除 RAG 向量集合及其全部数据。

用途：Milvus 不支持给已有集合加字段。schema 升级（如新增 parent_id / parent_content /
chunk_type / source_location / extra）后，必须先删除旧集合，再启动服务由
MilvusManager → DocumentMilvusStore.ensure_collection() 按最新 schema 自动重建。

安全约束：
- 默认 dry-run：只打印将删除的集合与当前集合列表，不做任何修改；
- 必须显式加 --yes 才真正删除（不可逆，集合内所有向量都会被清空）；
- 删除后集合为空，服务启动会自动重建；文档需重新触发解析
  （POST /api/v1/tenant/agent/files/parse），如需把 agent_file.parse_status 重置为 pending
  可加 --reset-parse-status。

用法：
    python scripts/drop_rag_collection.py                      # 预览
    python scripts/drop_rag_collection.py --yes                # 真正删除
    python scripts/drop_rag_collection.py --yes --reset-parse-status
    python scripts/drop_rag_collection.py --collection other_coll --yes
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# 确保 backend 包在 sys.path（脚本以项目根运行：python scripts/drop_rag_collection.py）
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pymilvus import AsyncMilvusClient  # noqa: E402

from backend.common.logger import logger  # noqa: E402
from backend.config import config  # noqa: E402


async def _list_collections(client: AsyncMilvusClient) -> list[str]:
    try:
        return list(await client.list_collections())
    except Exception as exc:  # noqa: BLE001 - 列举失败不影响删除主流程
        logger.warning(f"列举集合失败：{exc}")
        return []


async def _reset_parse_status() -> int:
    """把 agent_file 的解析状态重置为 pending，便于重新触发 /parse。"""
    from sqlalchemy import text

    from backend.data.sql import execute_write, session_scope

    async with session_scope() as session:
        n = await execute_write(
            session,
            text("UPDATE agent_file SET parse_status = 'pending' WHERE parse_status <> 'pending'"),
            {},
        )
        await session.commit()
        return int(n)


async def main() -> None:
    cfg = config.milvus
    ap = argparse.ArgumentParser(description="删除 RAG 向量集合及其全部数据")
    ap.add_argument("--collection", default="agent_memory", help=f"集合名（默认 {cfg.collection}）")
    ap.add_argument("--yes", action="store_true", help="确认真正删除（不加只做 dry-run 预览）")
    ap.add_argument(
        "--reset-parse-status",
        action="store_true",
        help="同时把 agent_file.parse_status 重置为 pending（便于重新解析导入）",
    )
    args = ap.parse_args()

    uri = f"http://{cfg.host}:{cfg.port}"
    logger.info(f"连接 Milvus uri={uri} db={cfg.db_name} collection={args.collection}")
    client = AsyncMilvusClient(uri=uri, db_name=cfg.db_name, token=cfg.token or None)
    try:
        collections = await _list_collections(client)
        logger.info(f"当前集合：{collections or '（空）'}")

        exists = await client.has_collection(args.collection)
        if not exists:
            logger.info(f"集合 [{args.collection}] 不存在，无需删除")
        elif not args.yes:
            logger.warning(
                f"[dry-run] 将删除集合 [{args.collection}] 及其全部数据；"
                "确认无误后重新执行并加 --yes"
            )
            return
        else:
            await client.drop_collection(args.collection)
            logger.warning(f"已删除集合 [{args.collection}]（全部向量数据已清空）")
            remaining = await _list_collections(client)
            logger.info(f"删除后集合：{remaining or '（空）'}")

        if args.reset_parse_status:
            n = await _reset_parse_status()
            logger.warning(f"已把 agent_file.parse_status 重置为 pending，共 {n} 条")
        logger.info("完成。启动服务后 MilvusManager 会按最新 schema 自动重建集合。")
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
