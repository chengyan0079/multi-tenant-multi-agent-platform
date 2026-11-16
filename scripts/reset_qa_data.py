# -*- coding: utf-8 -*-
"""重置统一咨询测试数据：会话 / 轮次 / 评测 / 长期记忆 / checkpoint / Redis 短期记忆。

用法（在项目根目录执行）：
  python scripts/reset_qa_data.py                     # 预览：只统计，不删除
  python scripts/reset_qa_data.py --yes               # 删除核心表 + Redis 短期记忆
  python scripts/reset_qa_data.py --yes --all         # 额外删变更单 / 待审队列 / outbox / 死信 / 接口日志
  python scripts/reset_qa_data.py --yes --no-redis    # 不清 Redis

注意：
  - 只清「运行时数据」，不动 agent / agent_menu / agent_user / agent_tool / agent_model_registry 等配置；
  - 文档与向量（agent_qa_file / agent_qa_chunk / Milvus）不在本脚本范围，需另行清理；
  - 执行前建议先跑一次不带 --yes 的预览。
"""

from __future__ import annotations

import argparse
import asyncio
import sys

sys.path.insert(0, r"e:\cywork\python\project\agent-platform")

from sqlalchemy import text

from backend.app_state import app_state
from backend.config import config
from backend.data.clients.postgres import PostgresClient

# 删除顺序：先子后父（无物理外键，仅保证语义清晰）
CORE_TABLES = [
    "agent_qa_ragas_evals",
    "agent_unified_turn",
    "agent_thread",
    "agent_long_term_memory",
    "checkpoint_writes",
    "checkpoint_blobs",
    "checkpoints",
]

EXTRA_TABLES = [
    "agent_knowledge_pending_queue",
    "agent_change_release",
    "agent_change_review",
    "agent_change_request",
    "agent_outbox",
    "agent_dead_letter",
    "agent_api_call_log",
]

SESSION_PATTERN = "t:*:u:*:session:*"


def _schema() -> str:
    return (config.postgres.search_path or "unified_schemas").split(",")[0].strip()


async def _counts(session, schema: str, tables: list[str]) -> dict[str, int | None]:
    out: dict[str, int | None] = {}
    for table in tables:
        try:
            n = await session.scalar(text(f"SELECT count(*) FROM {schema}.{table}"))
            out[table] = int(n or 0)
        except Exception:  # noqa: BLE001 - 表不存在
            out[table] = None
    return out


def _print(title: str, data: dict[str, int | None]) -> None:
    print(f"\n== {title} ==")
    for table, n in data.items():
        print(f"  {table:38s} {'(表不存在)' if n is None else n}")


async def _reset_redis() -> int:
    """清短期记忆 key（t:{tenant}:u:{user}:session:{thread}）。"""
    try:
        import redis.asyncio as aioredis

        client = aioredis.from_url(config.redis.url, decode_responses=True)
        deleted = 0
        batch: list[str] = []
        async for key in client.scan_iter(match=SESSION_PATTERN, count=500):
            batch.append(key)
            if len(batch) >= 500:
                deleted += await client.delete(*batch)
                batch.clear()
        if batch:
            deleted += await client.delete(*batch)
        await client.aclose()
        return deleted
    except Exception as exc:  # noqa: BLE001
        print(f"  Redis 清理失败：{exc}")
        return 0


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--yes", action="store_true", help="真正执行删除（否则只预览）")
    parser.add_argument("--all", action="store_true", help="额外清变更单/队列/outbox/死信/接口日志")
    parser.add_argument("--no-redis", action="store_true", help="不清 Redis 短期记忆")
    args = parser.parse_args()

    schema = _schema()
    tables = CORE_TABLES + (EXTRA_TABLES if args.all else [])
    print(f"目标 schema: {schema}")
    print(f"待清理表:   {', '.join(tables)}")
    print(f"Redis:      {'跳过' if args.no_redis else SESSION_PATTERN}")

    client = PostgresClient(str(config.postgres.async_url), search_path=config.postgres.search_path)
    app_state.clients.ensure("postgres", lambda: client)
    await client.connect()
    try:
        async with client.session_scope() as session:
            before = await _counts(session, schema, tables)
        _print("删除前", before)

        if not args.yes:
            print("\n（预览模式）加 --yes 才会真正删除。")
            return

        async with client.session_scope() as session:
            for table in tables:
                if before.get(table) is None:
                    continue
                await session.execute(text(f"DELETE FROM {schema}.{table}"))
                print(f"  deleted {table}: {before.get(table)}")
            await session.commit()

        async with client.session_scope() as session:
            after = await _counts(session, schema, tables)
        _print("删除后", after)

        if not args.no_redis:
            n = await _reset_redis()
            print(f"\n  Redis 短期记忆已删除 key 数：{n}")

        print("\n完成。重启后端后即为干净数据。")
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
