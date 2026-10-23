"""
registry - 离线功能块注册表（自描述、可调度）。

各功能块用 @register 装饰完成自注册；新增块只需建子包 + 在 tasks/__init__.py import。
提供 list_tasks / get_task / run_task 供调用方统一发现与执行，无需关心具体实现位置。
"""
from __future__ import annotations

from typing import Dict, List

from offline.base import OfflineTask


_REGISTRY: Dict[str, OfflineTask] = {}


def register(task: OfflineTask) -> OfflineTask:
    """注册一个功能块实例（装饰器用法：@register）。"""
    if not task.name:
        raise ValueError("OfflineTask.name 不能为空")
    if task.name in _REGISTRY:
        raise ValueError(f"离线功能块已注册: {task.name}")
    _REGISTRY[task.name] = task
    return task


def get_task(name: str) -> OfflineTask:
    if name not in _REGISTRY:
        raise KeyError(f"未知离线功能块: {name}（已注册: {list_tasks()}）")
    return _REGISTRY[name]


def list_tasks() -> List[str]:
    """返回所有已注册功能块名称（按字母序）。"""
    return sorted(_REGISTRY)


def run_task(name: str, cfg=None, **kwargs) -> Any:
    """按名称调度功能块。"""
    return get_task(name).run(cfg, **kwargs)
