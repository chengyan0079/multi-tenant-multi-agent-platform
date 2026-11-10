"""启动期就绪自检：模型（缺失则启动阻断）+ 插件（registry 非空则告警不阻断）。

不连库：mock ModelDao.count_enabled 与 load_all/PluginRegistry，仅验证自检分支逻辑。
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest

from backend.app_state import app_state
from backend.data.dao.agent.model_dao import ModelDao
from backend.mcp.registry import PluginRegistry
from backend.server.managers.model_manager import ModelManager
from backend.server.managers.plugin_manager import PluginManager, reload_plugins


async def test_check_ready_passes_when_all_present() -> None:
    """四类均有 enabled 记录时，自检通过、不抛异常。"""
    with patch.object(ModelDao, "count_enabled", new=AsyncMock(return_value=2)):
        await ModelManager._check_ready()


async def test_check_ready_blocks_when_one_type_missing() -> None:
    """任一类型无 enabled 记录时，启动阻断（抛 RuntimeError 含「启动阻断」）。"""
    def side(mt: str) -> int:
        return 0 if mt == "llm" else 1

    with patch.object(ModelDao, "count_enabled", new=AsyncMock(side_effect=side)):
        with pytest.raises(RuntimeError, match="启动阻断"):
            await ModelManager._check_ready()


async def test_check_ready_blocks_on_db_error() -> None:
    """查询 model_registry 抛错（DB 未就绪）时，自检失败并向上阻断启动。"""
    with patch.object(ModelDao, "count_enabled", new=AsyncMock(side_effect=RuntimeError("db down"))):
        with pytest.raises(RuntimeError):
            await ModelManager._check_ready()


async def test_plugin_manager_start_warns_when_empty(monkeypatch) -> None:
    """registry 为空时不阻断启动，但记录 warning 日志（当前 reload_plugins 口径）。"""
    monkeypatch.setattr(app_state, "plugin_registry", None)
    reg = PluginRegistry()
    with patch("backend.server.managers.plugin_manager._build_registry",
               new=AsyncMock(return_value=reg)), \
         patch("backend.server.managers.plugin_manager.logger") as mock_logger:
        assert await reload_plugins() == 0
        mock_logger.warning.assert_called_once()
    # PluginManager.start 只是 reload_plugins 的启动期包装，不额外抛异常
    with patch("backend.server.managers.plugin_manager.reload_plugins",
               new=AsyncMock(return_value=0)):
        await PluginManager().start()


async def test_plugin_manager_start_no_warn_when_loaded(monkeypatch) -> None:
    """registry 非空时不记录「插件注册表为空」告警。"""
    monkeypatch.setattr(app_state, "plugin_registry", None)
    reg = PluginRegistry()
    with patch("backend.server.managers.plugin_manager._build_registry",
               new=AsyncMock(return_value=reg)), \
         patch.object(PluginRegistry, "plugin_count", new_callable=PropertyMock,
                      return_value=1), \
         patch("backend.server.managers.plugin_manager.logger") as mock_logger:
        assert await reload_plugins() == 1
        mock_logger.warning.assert_not_called()
