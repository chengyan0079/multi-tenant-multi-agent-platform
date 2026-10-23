"""
task - 离线评审主逻辑（占位骨架）。

与 intent_training / intent_eval 同构：实现 OfflineTask 并自注册，统一暴露 main()。
当前未实现具体评审业务，调用即抛 NotImplementedError，后续按同样结构补入，
例如：离线批量跑评测集 → 汇总人工标注 → 产出评审报告（准确率/偏差/风险项）。
"""
from __future__ import annotations

from typing import Any

# 允许直接 `python offline/tasks/review/task.py` 启动（非 -m 时把项目根加入 sys.path）
import sys
from pathlib import Path

if str(Path(__file__).resolve().parents[3]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from offline.base import OfflineTask
from offline.common.config import OfflineConfig
from offline.registry import register


@register
class ReviewTask(OfflineTask):
    name = "review"
    description = "离线评审（人工/HITL 评审、模型输出复核等），当前为占位骨架"

    def run(self, cfg: OfflineConfig | None = None, **kwargs) -> None:
        cfg = cfg or OfflineConfig.from_env()
        raise NotImplementedError(
            "评审功能块尚未实现；请按 intent_training 的结构在此补充评审逻辑"
        )


main = ReviewTask().run


if __name__ == "__main__":
    main()
