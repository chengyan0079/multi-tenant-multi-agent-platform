"""配置分组（data_id 的 group 维度）。"""
from __future__ import annotations

from enum import Enum


class ConfigGroup(str, Enum):
    """配置中心分组：SYSTEM 兜底组，PROMPT 提示词等按业务扩展。"""

    SYSTEM = "SYSTEM"
    PROMPT = "PROMPT"
