"""
offline - 离线模块（与在线业务解耦，按功能块分子包，统一用 registry 调度）。

设计目标：前瞻与可扩展。每个离线功能块（意图训练、意图评估、评审、agent 全流程审计…）
都是 offline/tasks/ 下的一个子包，实现 OfflineTask 并自注册，彼此独立、互不耦合。
新增块 = 建子包 + 实现 OfflineTask + 在 tasks/__init__.py import，无需改动其他代码。

边界：本目录只做离线生产，不依赖后端 FastAPI/数据库；在线侧 LLMFactory 仅按
CLASSIFIER_DIR 懒加载产物（读 meta.json 得到标签顺序），二者除「模型文件」外零耦合。

无独立 CLI 启动器；入口：
  from offline import list_tasks, run_task, get_task, OfflineConfig
  list_tasks()                                  # 查看所有已注册功能块
  run_task("intent_training")                   # 跑意图训练
  run_task("intent_eval")                        # 跑评估
  run_task("agent_audit")                        # 未来审计（现 NotImplementedError）

也可直接调用某块的 main 入口：
  from offline.tasks.intent_training.task import main as train
  train()
依赖见 requirements.txt（torch / transformers / scikit-learn / pandas）。
"""
from __future__ import annotations

from offline.common import OfflineConfig
from offline.registry import get_task, list_tasks, register, run_task
from offline import tasks  # 触发各功能块 @register 自注册

__all__ = ["OfflineConfig", "register", "get_task", "list_tasks", "run_task", "tasks"]
