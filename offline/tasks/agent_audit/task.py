"""
task - agent 全流程审计（占位骨架，预留扩展位置）。

定位：离线回放并分析 agent 运行轨迹（threads/runs/nodes/trace/escalation），
产出审计报告（合规、质量、时延、成本、风险项）。这是「离线功能块」前瞻性的示例：
与意图训练/评估完全平级，同属 offline.tasks 下自注册的一个块。

后续实现要点（建议，不在此展开）：
  - 数据源：读 PostgreSQL（threads/runs/messages/escalations）与 trace/埋点日志；
  - 分析：按 tenant/agent/用户聚合，统计成功率、人工介入率、越权/越界、异常链路；
  - 产物：写回审计表或离线报告（JSON/CSV），供在线只读展示。
"""
from __future__ import annotations

from typing import Any

# 允许直接 `python offline/tasks/agent_audit/task.py` 启动（非 -m 时把项目根加入 sys.path）
import sys
from pathlib import Path

if str(Path(__file__).resolve().parents[3]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from offline.base import OfflineTask
from offline.common.config import OfflineConfig
from offline.registry import register


@register
class AgentAuditTask(OfflineTask):
    name = "agent_audit"
    description = "agent 全流程审计：离线回放/分析运行轨迹，产出审计报告（待实现）"

    def run(self, cfg: OfflineConfig | None = None, **kwargs) -> None:
        cfg = cfg or OfflineConfig.from_env()
        raise NotImplementedError(
            "agent 全流程审计尚未实现；按 intent_training 的结构在此补入回放与分析逻辑"
        )


main = AgentAuditTask().run


if __name__ == "__main__":
    main()
