"""
tasks - 离线功能块集合（每个子包实现一个 OfflineTask 并自注册）。

新增功能块：在下方加一行子包 import 即可触发其 @register；无需改动其他代码。
当前已规划：意图训练 / 意图评估 / 评审 / agent 全流程审计（占位）。
"""
from __future__ import annotations

from offline.tasks import agent_audit  # noqa: F401  未来：agent 全流程审计
from offline.tasks import intent_eval  # noqa: F401  意图模型评估
from offline.tasks import intent_training  # noqa: F401  意图模型训练
from offline.tasks import review  # noqa: F401  评审（人工/HITL）

__all__ = ["intent_training", "intent_eval", "review", "agent_audit"]
