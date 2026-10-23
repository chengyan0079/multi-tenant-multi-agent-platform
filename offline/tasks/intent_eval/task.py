"""
task - 意图分类模型评估（准确率/分类报告/混淆矩阵 → metrics.json）。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, List

import torch

# 允许直接 `python offline/tasks/intent_eval/task.py` 启动（非 -m 时把项目根加入 sys.path）
import sys
from pathlib import Path

if str(Path(__file__).resolve().parents[3]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from offline.base import OfflineTask
from offline.common.config import OfflineConfig
from offline.common.data import load_records
from offline.common.model import load_artifact
from offline.registry import register


def _predict(model, tokenizer, text: str, max_len: int, device: str) -> int:
    enc = tokenizer(
        text, return_tensors="pt", truncation=True, padding="max_length", max_length=max_len
    )
    enc = {k: v.to(device) for k, v in enc.items()}
    with torch.no_grad():
        logits = model(**enc).logits
    return int(logits.argmax(dim=-1).item())


@register
class IntentEvalTask(OfflineTask):
    name = "intent_eval"
    description = "评估意图分类器产物（准确率/分类报告/混淆矩阵），写 metrics.json"

    def run(self, cfg: OfflineConfig | None = None, **kwargs) -> dict:
        from sklearn.metrics import accuracy_score, classification_report, confusion_matrix

        cfg = cfg or OfflineConfig.from_env()
        model, tokenizer, labels, max_len = load_artifact(cfg.model_out)
        device = "cuda" if torch.cuda.is_available() else "cpu"
        model.to(device)

        records = load_records(cfg.data)
        y_true: List[int] = [r[1] for r in records]
        y_pred: List[int] = [_predict(model, tokenizer, r[0], max_len, device) for r in records]

        acc = accuracy_score(y_true, y_pred)
        report = classification_report(
            y_true, y_pred, target_names=labels, output_dict=True, zero_division=0
        )
        cm = confusion_matrix(y_true, y_pred).tolist()
        metrics = {
            "accuracy": acc,
            "report": report,
            "confusion_matrix": cm,
            "labels": labels,
        }

        out = Path(cfg.model_out) / "metrics.json"
        out.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")

        print(f"[{self.name}] 准确率={acc:.4f}")
        print(classification_report(y_true, y_pred, target_names=labels, zero_division=0))
        print(f"[{self.name}] 指标已写入 {out}")
        return metrics


main = IntentEvalTask().run


if __name__ == "__main__":
    main()
