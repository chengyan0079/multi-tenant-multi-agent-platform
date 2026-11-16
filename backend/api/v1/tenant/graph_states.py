"""图状态（LangGraph checkpoints）查询：按租户 + thread_id 筛选。"""

from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Integer, String, bindparam, text

from backend.common.response import success
from backend.config import config
from backend.data.sql import fetch_all, fetch_one, session_scope
from backend.middleware.auth import CurrentUser, get_current_user
from backend.security.rbac import Scope
from backend.security.security import require_scope

router = APIRouter(prefix="/graph-states", tags=["tenant"])

# 明确使用配置的 schema，避免同名表（如历史残留的 agent_platform.checkpoints）混淆
_PRIMARY_SCHEMA = (config.postgres.search_path or "unified_schemas").split(",")[0].strip()
_CHECKPOINT_TABLE = f"{_PRIMARY_SCHEMA}.checkpoints"

# 租户隔离：metadata.tenant_id 或 thread_id 前缀 t{tenant}:
_WHERE = (
    "WHERE ((metadata->>'tenant_id') = :tid OR thread_id LIKE :prefix) "
    # 会话用户级：非租户管理员只看自己（metadata.user_id 或 thread 前缀 t{tenant}:u{uid}:）
    "AND (:uid IS NULL OR (metadata->>'user_id') = :uid OR thread_id LIKE :uprefix) "
    # thread_id 支持模糊匹配（UUID 片段即可，子图分区含 :agent:turn 后缀）
    "AND (:thread_id IS NULL OR thread_id ILIKE '%' || :thread_id || '%')"
)

_SELECT = text(
    "SELECT thread_id, checkpoint_ns, checkpoint_id, parent_checkpoint_id, type, metadata "
    f"FROM {_CHECKPOINT_TABLE} {_WHERE} ORDER BY checkpoint_id DESC LIMIT :limit OFFSET :offset"
).bindparams(
    bindparam("tid", type_=String),
    bindparam("prefix", type_=String),
    bindparam("uid", type_=String),
    bindparam("uprefix", type_=String),
    bindparam("thread_id", type_=String),
    bindparam("limit", type_=Integer),
    bindparam("offset", type_=Integer),
)

_COUNT = text(f"SELECT count(*) FROM {_CHECKPOINT_TABLE} {_WHERE}").bindparams(
    bindparam("tid", type_=String),
    bindparam("prefix", type_=String),
    bindparam("uid", type_=String),
    bindparam("uprefix", type_=String),
    bindparam("thread_id", type_=String),
)


@router.get("", summary="图状态列表（checkpoints）")
async def list_graph_states(
    thread_id: Optional[str] = Query(None, description="按 thread_id 精确筛选"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    current: CurrentUser = Depends(get_current_user),
    _: object = Depends(require_scope(Scope.UNIFIED_SESSION_PAGE)),
):
    is_admin = bool(current.is_tenant_admin or current.is_super_admin)
    params = {
        "tid": str(current.tenant_id),
        "prefix": f"t{current.tenant_id}:%",
        "uid": None if is_admin else str(current.user_id),
        "uprefix": f"t{current.tenant_id}:u{current.user_id}:%",
        "thread_id": thread_id or None,
    }
    page_params = {**params, "limit": page_size, "offset": (page - 1) * page_size}
    async with session_scope() as session:
        rows = await fetch_all(session, _SELECT, page_params)
        total_row = await fetch_one(session, _COUNT, params)

    # jsonb 经 text() 查询返回的是字符串：解析成对象，前端才能取 metadata.agent_type
    for row in rows:
        meta = row.get("metadata")
        if isinstance(meta, str):
            try:
                row["metadata"] = json.loads(meta)
            except (json.JSONDecodeError, TypeError):
                row["metadata"] = {}
        row["type"] = row.get("type") or "checkpoint"
        row["checkpoint_ns"] = row.get("checkpoint_ns") or "(root)"
    return success(
        {
            "items": rows,
            "total": int((total_row or {}).get("count") or 0),
            "page": page,
            "page_size": page_size,
        }
    )
