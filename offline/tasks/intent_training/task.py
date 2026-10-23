"""
task - 离线训练意图分类器（意图识别模型的微调与产物产出）。
"""
from __future__ import annotations

from typing import Any

# 允许直接 `python offline/tasks/intent_training/task.py` 启动（非 -m 时把项目根加入 sys.path）
import sys
from pathlib import Path

if str(Path(__file__).resolve().parents[3]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from offline.base import OfflineTask
from offline.common.config import OfflineConfig
from offline.registry import register


@register
class IntentTrainingTask(OfflineTask):
    name = "intent_training"
    description = "离线微调意图分类器并写出 HF 产物（含 meta.json）"

    def run(self, cfg: OfflineConfig | None = None, **kwargs) -> None:
        from transformers import AutoTokenizer, Trainer, TrainingArguments

        from offline.common.data import IntentDataset, load_records
        from offline.common.intents import INTENT_LABELS
        from offline.common.model import build_model, save_artifact

        cfg = cfg or OfflineConfig.from_env()
        records = load_records(cfg.data)
        tokenizer = AutoTokenizer.from_pretrained(cfg.base_model)
        train_ds = IntentDataset(records, tokenizer, cfg.max_len)
        model = build_model(cfg.base_model, len(INTENT_LABELS))

        training_args = TrainingArguments(
            output_dir=str(cfg.model_out),
            num_train_epochs=cfg.epochs,
            per_device_train_batch_size=cfg.batch,
            learning_rate=cfg.lr,
            logging_steps=10,
            save_strategy="no",
            report_to="none",
        )
        Trainer(model=model, args=training_args, train_dataset=train_ds).train()

        save_artifact(model, tokenizer, cfg.model_out, cfg.max_len)
        print(f"[{self.name}] 训练完成，产物已写入 {cfg.model_out}")


# 便捷入口（保留 main 方法）
main = IntentTrainingTask().run


if __name__ == "__main__":
    main()
