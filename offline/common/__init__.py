"""
common - 离线模块公共基础（各能力子包共享）。

包含：配置 OfflineConfig、意图标签 schema、数据集加载、HF 产物构建/保存/加载。
"""
from __future__ import annotations

from offline.common.config import OfflineConfig
from offline.common.intents import INTENT_LABELS, INTENT2ID, ID2INTENT
from offline.common.data import IntentDataset, load_records
from offline.common.model import build_model, load_artifact, save_artifact

__all__ = [
    "OfflineConfig",
    "INTENT_LABELS",
    "INTENT2ID",
    "ID2INTENT",
    "IntentDataset",
    "load_records",
    "build_model",
    "load_artifact",
    "save_artifact",
]
