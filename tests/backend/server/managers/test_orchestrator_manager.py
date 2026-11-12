"""OrchestratorManager.health() 收口测试（无头，mock app_state）。

锁死 §12 R15 / §14 Q6：注册表对象存在但库规格加载失败时，health 必须报 `degraded`
（能力降级），而非 `down`（仅对象未初始化才 `down`）。
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from backend.app_state import app_state
from backend.server.managers import orchestrator_manager as om_mod


class _FakeRegistry:
    def __init__(self, db_loaded: bool) -> None:
        self.db_loaded = db_loaded


async def test_health_down_when_orchestrator_missing(monkeypatch) -> None:
    monkeypatch.setattr(app_state, "orchestrator", None)
    monkeypatch.setattr(app_state, "agent_registry", _FakeRegistry(db_loaded=True))
    info = await om_mod.OrchestratorManager().health()
    assert info.status == "down"


async def test_health_degraded_when_registry_db_unloaded(monkeypatch) -> None:
    monkeypatch.setattr(app_state, "orchestrator", MagicMock())
    monkeypatch.setattr(app_state, "agent_registry", _FakeRegistry(db_loaded=False))
    info = await om_mod.OrchestratorManager().health()
    assert info.status == "degraded"
    assert "库加载失败" in info.detail


async def test_health_running_when_loaded(monkeypatch) -> None:
    monkeypatch.setattr(app_state, "orchestrator", MagicMock())
    monkeypatch.setattr(app_state, "agent_registry", _FakeRegistry(db_loaded=True))
    info = await om_mod.OrchestratorManager().health()
    assert info.status == "running"
