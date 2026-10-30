"""agent 与模型的绑定 DAO（agent_model 表）。

- 全局表（无 tenant 列），只描述 agent 默认使用哪个 model_registry 模型；
- resolve() 按 (agent_type, model_type) 解析出该 agent 实际使用的模型配置：
  is_default 优先、其次 priority 最小，无绑定则回退到 model_registry 的 active；
- 本文件在 resolve 之外补充了「绑定关系维护」所需的增删改查接口。
"""
from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import text

from backend.data.sql import execute_write, fetch_all, fetch_one, fetch_value, session_scope
from backend.data.sql.audit import audit_on_insert, audit_on_update

_COLS = (
    "r.id, r.model_type, r.name, r.provider, r.base_url, r.api_key, "
    "r.endpoint_path, r.temperature, r.timeout_s, r.max_retries, r.enabled"
)
_RESOLVE = text(
    f"""
    SELECT {_COLS}
    FROM agent_model m
    JOIN agent a ON a.id = m.agent_id
    JOIN agent_model_registry r ON r.id = m.model_id
    WHERE a.agent_type = :agent_type
      AND r.model_type = :model_type
      AND r.enabled = true
    ORDER BY m.is_default DESC, m.priority ASC, m.model_id ASC
    LIMIT 1
    """
)

_LIST_BY_AGENT = text("""
SELECT m.agent_id, m.model_id, m.is_default, m.priority,
       r.model_type, r.name, r.provider, r.enabled AS model_enabled
FROM agent_model m
JOIN agent a ON a.id = m.agent_id
JOIN agent_model_registry r ON r.id = m.model_id
WHERE a.agent_type = :agent_type
ORDER BY r.model_type, m.priority ASC, m.model_id ASC
""")

_COUNT_REL = text("SELECT COUNT(*) FROM agent_model WHERE agent_id = :agent_id")

_GET_REL = text(
    "SELECT agent_id, model_id, is_default, priority FROM agent_model "
    "WHERE agent_id = :agent_id AND model_id = :model_id"
)

_INSERT_REL = text("""
INSERT INTO agent_model (
    agent_id, model_id, is_default, priority, create_user_id, update_user_id
) VALUES (
    :agent_id, :model_id, :is_default, :priority, :create_user_id, :update_user_id
)
ON CONFLICT (agent_id, model_id) DO UPDATE
SET is_default = EXCLUDED.is_default, priority = EXCLUDED.priority, update_user_id = EXCLUDED.update_user_id
""")

_DELETE_REL = text(
    "DELETE FROM agent_model WHERE agent_id = :agent_id AND model_id = :model_id"
)

_UPDATE_REL = text("""
UPDATE agent_model SET
    is_default = :is_default, priority = :priority, update_user_id = :update_user_id
WHERE agent_id = :agent_id AND model_id = :model_id
""")

# 设为默认时，把同类其他绑定置为非默认（同 agent_id + 同 model_type，排除自身）
_RESET_DEFAULT = text("""
UPDATE agent_model SET is_default = false, update_user_id = :update_user_id
WHERE agent_id = :agent_id
  AND model_id <> :exclude_model_id
  AND model_id IN (
      SELECT id FROM agent_model_registry WHERE model_type = :model_type
  )
""")


class AgentModelRelDao:
    """agent → model 绑定解析与维护。"""

    @staticmethod
    async def resolve(agent_type: str, model_type: str = "llm") -> Optional[dict[str, Any]]:
        """取某 agent 在某模型类型下实际绑定的模型配置。

        优先 is_default，其次 priority 最小；无绑定（或绑定模型已禁用）返回 None，
        调用方据此回退到 model_registry 的全局 active。
        """
        async with session_scope() as session:
            return await fetch_one(session, _RESOLVE, {"agent_type": agent_type, "model_type": model_type})

    @staticmethod
    async def list_by_agent(agent_type: str) -> list[dict[str, Any]]:
        """该 agent 的全部模型绑定（含模型展示信息，按 model_type/priority 排序）。"""
        async with session_scope() as session:
            return await fetch_all(session, _LIST_BY_AGENT, {"agent_type": agent_type})

    @staticmethod
    async def count_by_agent(agent_id: int) -> int:
        """统计某 agent 的绑定数（删除前校验是否可删）。"""
        async with session_scope() as session:
            return int(await fetch_value(session, _COUNT_REL, {"agent_id": agent_id}) or 0)

    @staticmethod
    async def get(agent_id: int, model_id: int) -> Optional[dict[str, Any]]:
        """取单条绑定（含 is_default/priority），不存在返回 None。"""
        async with session_scope() as session:
            return await fetch_one(session, _GET_REL, {"agent_id": agent_id, "model_id": model_id})

    @staticmethod
    async def add(
        agent_id: int, model_id: int, *, is_default: bool, priority: int
    ) -> None:
        """新增或覆盖一条绑定（同一 agent+model 冲突则更新默认/优先级）。"""
        async with session_scope() as session:
            await execute_write(
                session,
                _INSERT_REL,
                {
                    "agent_id": agent_id,
                    "model_id": model_id,
                    "is_default": is_default,
                    "priority": priority,
                    **audit_on_insert(with_tenant=False),
                },
            )

    @staticmethod
    async def remove(agent_id: int, model_id: int) -> int:
        """解绑，返回影响行数。"""
        async with session_scope() as session:
            return await execute_write(
                session, _DELETE_REL, {"agent_id": agent_id, "model_id": model_id}
            )

    @staticmethod
    async def set_default_priority(
        agent_id: int, model_id: int, *, is_default: Optional[bool], priority: Optional[int]
    ) -> int:
        """更新默认/优先级；None 字段保留原值。返回影响行数（0 表示绑定不存在）。"""
        cur = await AgentModelRelDao.get(agent_id, model_id)
        if cur is None:
            return 0
        new_default = is_default if is_default is not None else cur["is_default"]
        new_priority = priority if priority is not None else cur["priority"]
        async with session_scope() as session:
            return await execute_write(
                session,
                _UPDATE_REL,
                {
                    "agent_id": agent_id,
                    "model_id": model_id,
                    "is_default": new_default,
                    "priority": new_priority,
                    **audit_on_update(with_tenant=False),
                },
            )

    @staticmethod
    async def reset_default(agent_id: int, model_type: str, exclude_model_id: int) -> int:
        """把同类其他绑定置为非默认（设默认项时的互斥处理）。"""
        async with session_scope() as session:
            return await execute_write(
                session,
                _RESET_DEFAULT,
                {
                    "agent_id": agent_id,
                    "model_type": model_type,
                    "exclude_model_id": exclude_model_id,
                    **audit_on_update(with_tenant=False),
                },
            )
