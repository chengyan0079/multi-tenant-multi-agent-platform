"""
base_manager - Manager 抽象基类

各启动项继承并实现 start()/stop()；约定 stop() 幂等且吞掉自身异常，由 AppServer 统一兜底记录。
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class BaseManager(ABC):
    """启动项基类，统一生命周期接口。"""

    @abstractmethod
    async def start(self) -> None:
        """初始化资源并写入 app_state。失败抛异常由 AppServer 处理。"""
        raise NotImplementedError

    async def stop(self) -> None:
        """释放资源；默认空实现，子类按需覆盖。"""
        return None
