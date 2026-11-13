"""agents 包：业务 Agent 自动发现与加载。

识别机制（与路径无关）：
    每个具体 Agent 继承 ``Agent``（backend.agents.base.Agent），在类定义时经
    ``Agent.__init_subclass__`` 自动登记到 ``Agent._registry``。
    ``iter_agent_classes()`` 仅读取该集合，**不扫描任何文件路径/命名约定**。

加载机制（仅触发 import）：
    新增 Agent 只要位于 ``backend.agents`` 包下任意子模块即可；``load_agent_modules()``
    遍历直接子包并 import，触发子类定义与自动登记。识别逻辑本身不依赖此遍历。
"""

from __future__ import annotations

import importlib
import pkgutil

from backend.agents.base import Agent


def load_agent_modules() -> None:
    """导入 ``backend.agents`` 下所有直接子包，触发各 Agent 子类的自动登记。

    仅负责「加载」：import 时子类经 ``__init_subclass__`` 登记，**不做任何路径/
    文件名识别**；识别交给 ``iter_agent_classes``（基于 ``Agent._registry``）。
    """
    import backend.agents as _pkg

    for entry in pkgutil.iter_modules(_pkg.__path__):
        if entry.name == "base" or not entry.ispkg:
            continue
        try:
            importlib.import_module(f"backend.agents.{entry.name}")
        except ModuleNotFoundError:
            continue


def iter_agent_classes() -> list[type[Agent]]:
    """返回所有已登记（继承 Agent 的具体）子类，识别仅依赖继承关系。"""
    return list(Agent._registry)
