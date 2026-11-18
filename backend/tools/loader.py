"""插件扫描加载：扫描 builtin 子包并预留外部插件挂载点，单插件失败不影响其余。"""

from __future__ import annotations

import importlib
import os
from typing import List, Optional

import yaml

from backend.common.logger import get_logger
from backend.tools.protocol import AgentPlugin, PluginManifest
from backend.tools.registry import PluginRegistry

logger = get_logger("plugin_loader")

_BUILTIN = os.path.join(os.path.dirname(__file__), "builtin")


def _load_manifest(pkg_dir: str) -> Optional[PluginManifest]:
    path = os.path.join(pkg_dir, "manifest.yaml")
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return PluginManifest(
        name=data.get("name", ""),
        version=data.get("version", "0.1.0"),
        capabilities=data.get("capabilities", []),
        dependencies=data.get("dependencies", []),
        description=data.get("description", ""),
    )


def discover_builtin() -> List[AgentPlugin]:
    """返回 builtin 目录下全部插件实例（每个子包 __init__ 导出 plugin）。"""
    plugins: List[AgentPlugin] = []
    if not os.path.isdir(_BUILTIN):
        return plugins
    for name in sorted(os.listdir(_BUILTIN)):
        pkg_dir = os.path.join(_BUILTIN, name)
        if not os.path.isdir(pkg_dir) or not os.path.exists(os.path.join(pkg_dir, "__init__.py")):
            continue
        try:
            module = importlib.import_module(f"backend.tools.builtin.{name}")
            plugin = getattr(module, "plugin", None)
            if plugin is None:
                logger.warning(f"插件未导出 plugin 实例: {name}")
                continue
            plugins.append(plugin)
            logger.info(f"发现插件: {name}")
        except Exception as exc:
            logger.exception(f"插件加载失败(已跳过): {name} - {exc}")
    return plugins


async def load_all(registry: PluginRegistry) -> None:
    """扫描 builtin 并注册到 PluginRegistry（失败单插件不阻断）。"""
    for plugin in discover_builtin():
        try:
            registry.register_plugin(plugin)
        except Exception as exc:
            logger.exception(f"插件注册失败(已跳过): {plugin.manifest.name} - {exc}")
