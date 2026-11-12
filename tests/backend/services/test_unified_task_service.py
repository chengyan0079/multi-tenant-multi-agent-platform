"""统一任务型入口的无头回归测试（Step 9 联调）。

覆盖 exam/resume 两类任务流：校验 turn_id 必须下传到业务表 INSERT 列与
broker enqueue 数据。早版本遗漏 turn_id 参数，导致 F821（enqueue 引用未定义
变量）且 INSERT 缺 NOT NULL 列，运行时直接失败；本测试锁死该回归。
"""
from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

from backend.services import unified_task_service as svc  # noqa: E402


def _fake_spec(agent_type: str) -> types.SimpleNamespace:
    return types.SimpleNamespace(agent_type=agent_type)


def _fake_session_scope() -> tuple[MagicMock, MagicMock]:
    """构造一个假的 session_scope 异步上下文：execute 的 fetchone 返回非空（模拟试卷存在）。"""
    session = MagicMock()
    result = MagicMock()
    result.fetchone.return_value = ("existing",)
    session.execute = AsyncMock(return_value=result)

    cm = AsyncMock()
    cm.__aenter__.return_value = session
    cm.__aexit__.return_value = False
    return cm, session


async def _run(agent_type: str, turn_id: str) -> tuple[dict, MagicMock]:
    cm, session = _fake_session_scope()
    with patch.object(svc, "session_scope", return_value=cm), \
         patch.object(svc, "_object_key_of", new_callable=AsyncMock, return_value="fake-key"), \
         patch.object(svc, "_entry_value", return_value="EXAM-ID"), \
         patch.object(svc, "enqueue_task", new_callable=AsyncMock) as enq:
        result = await svc.start_unified_task(
            spec=_fake_spec(agent_type),
            turn_id=turn_id,
            entry=None,
            attachments=[],
            tenant_id=6,
            user_id=4,
            trace_id="TRACE",
            thread_id="U-1",
        )
    return result, session, enq


def _insert_sql(session: MagicMock) -> str:
    sqls = [c.args[0].text for c in session.execute.call_args_list]
    insert_sqls = [s for s in sqls if "INSERT INTO" in s]
    assert insert_sqls, f"未捕获到 INSERT 语句：{sqls}"
    return insert_sqls[0]


async def test_start_exam_passes_turn_id() -> None:
    result, session, enq = await _run("exam", "T-EXAM")

    assert result["artifact_type"] == "exam"
    # 业务表 INSERT 必须带 turn_id 列（schema 为 NOT NULL）
    assert "turn_id" in _insert_sql(session)
    # broker 回写数据必须带 turn_id
    assert enq.call_args.kwargs["data"]["turn_id"] == "T-EXAM"


async def test_start_resume_passes_turn_id() -> None:
    result, session, enq = await _run("resume", "T-RESUME")

    assert result["artifact_type"] == "resume"
    assert "turn_id" in _insert_sql(session)
    assert enq.call_args.kwargs["data"]["turn_id"] == "T-RESUME"


async def test_resume_timeout_scan_marks_failed() -> None:
    """resume 评审超时兜底：扫描把 processing 且超时的记录批量标 failed。"""
    from backend.server.managers import scheduler_manager as sch

    captured: dict = {}

    async def _fake_write(session, sql, params):
        captured["sql"] = str(sql)
        captured["params"] = params
        return 3  # 模拟命中 3 条超时记录

    cm = AsyncMock()
    session = MagicMock()
    cm.__aenter__.return_value = session
    cm.__aexit__.return_value = False

    fake_app_state = types.SimpleNamespace(
        settings=types.SimpleNamespace(
            scheduler=types.SimpleNamespace(resume_timeout_min=10)
        )
    )

    with patch.object(sch, "app_state", fake_app_state), \
         patch.object(sch, "session_scope", return_value=cm), \
         patch.object(sch, "execute_write", _fake_write):
        mgr = sch.SchedulerManager()
        await mgr._scan_resume_timeout()

    assert "agent_resume_reviews" in captured["sql"]
    assert "UPDATE" in captured["sql"]
    assert captured["params"]["timeout"] == 10
