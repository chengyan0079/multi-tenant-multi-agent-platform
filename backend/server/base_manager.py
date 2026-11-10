"""Manager 抽象基类：子类实现 start()/stop()（stop 幂等），内置 name/status 状态追踪。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum


class ManagerStatus(str, Enum):
    """Manager 生命周期状态。"""

    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    FAILED = "failed"


@dataclass
class HealthInfo:
    """单个组件的健康探测结果。"""

    status: str  # running / degraded / down / stopped ...
    detail: str | None = None


class BaseManager(ABC):
    """启动项基类，统一生命周期接口与状态追踪。"""

    def __init__(self, name: str | None = None) -> None:
        self._name = name or self.__class__.__name__
        self._status: ManagerStatus = ManagerStatus.STOPPED

    @property
    def name(self) -> str:
        """显示名（默认取类名）。"""
        return self._name

    @property
    def status(self) -> ManagerStatus:
        """当前生命周期状态。"""
        return self._status

    @abstractmethod
    async def start(self) -> None:
        """初始化资源并写入 app_state。失败抛异常由 AppServer 处理。"""
        raise NotImplementedError

    async def stop(self) -> None:
        """释放资源；默认空实现，子类按需覆盖。"""
        pass

    async def health(self) -> HealthInfo:
        """健康探测。默认返回生命周期状态；子类可覆写做真实探活（如 ping DB/Redis）。

        返回 HealthInfo：status 用 ManagerStatus 的英文值或自定义（degraded/down），
        detail 可附错误信息，供 /health 与启动后状态日志展示。
        """
        return HealthInfo(status=self._status.value)

    # ---- 内部状态流转（由 AppServer 调用，子类一般不覆写）----

    def _set_status(self, status: ManagerStatus) -> None:
        self._status = status
