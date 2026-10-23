"""
intents - 意图标签 schema（与在线路由对齐，见 backend/api/v1/unified_chat.py）。

重要：INTENT_LABELS 的索引顺序即模型输出维度顺序；修改会破坏已训模型，
离线训练与在线加载都必须使用同一顺序。在线侧通过产物 meta.json 读取该顺序，
不依赖本文件导入，从而保持解耦。
"""
from __future__ import annotations

# 与 unified_chat 路由可达的 agent_type 一致：resume / qa / exam / interview
INTENT_LABELS: list[str] = ["resume", "exam", "interview", "qa"]
INTENT2ID: dict[str, int] = {label: i for i, label in enumerate(INTENT_LABELS)}
ID2INTENT: dict[int, str] = {i: label for i, label in enumerate(INTENT_LABELS)}
