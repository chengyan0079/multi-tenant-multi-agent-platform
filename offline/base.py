"""
base - 离线功能块的统一定义（接口/契约）。

设计目标：前瞻与可扩展。未来任意离线功能块（意图训练、评估、评审、agent 全流程审计…）
都只需在 offline/tasks/ 下建一个子包，定义一个继承 OfflineTask 的类并用 @register 自注册，
其余代码无需改动即可被 registry 发现与调度（run_task / list_tasks）。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TaskInfo:
    """功能块元信息（用于 list_tasks 展示）。"""

    name: str
    description: str


class OfflineTask(ABC):
    """离线功能块统一接口。子类覆盖 name/description 并实现 run()。"""

    name: str = ""
    description: str = ""

    @abstractmethod
    def run(self, cfg: Any | None = None, **kwargs) -> Any:
        """执行功能块。

        cfg: 配置对象（默认 OfflineConfig.from_env()）；kwargs: 任务专属参数透传。
        """

    def info(self) -> TaskInfo:
        return TaskInfo(name=self.name, description=self.description)
