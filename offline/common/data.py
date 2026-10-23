"""
data - 意图数据集加载（JSONL → torch Dataset）。

样本格式（每行一个 JSON 对象）：
  {"text": "...", "intent": "resume"}   或   {"query": "...", "label": "qa"}
intent/label 必须是 offline.common.intents.INTENT_LABELS 之一。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import List, Tuple

import torch

from offline.common.intents import INTENT2ID, INTENT_LABELS


def load_records(path: Path) -> List[Tuple[str, int]]:
    """读取 JSONL 标注为 (text, label_id) 列表。"""
    records: List[Tuple[str, int]] = []
    with open(path, "r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            text = obj.get("text") or obj.get("query")
            label = obj.get("intent") or obj.get("label")
            if text is None or label is None:
                raise ValueError(f"第 {lineno} 行缺少 text/intent: {obj}")
            if label not in INTENT2ID:
                raise ValueError(f"第 {lineno} 行未知意图 {label!r}（允许: {INTENT_LABELS}）")
            records.append((text, INTENT2ID[label]))
    if not records:
        raise ValueError(f"数据集为空: {path}")
    return records


class IntentDataset(torch.utils.data.Dataset):
    """文本 → tokenize 后的模型输入；labels 为意图 id。"""

    def __init__(self, records: List[Tuple[str, int]], tokenizer, max_len: int) -> None:
        texts = [r[0] for r in records]
        self.labels = [r[1] for r in records]
        self.enc = tokenizer(
            texts, truncation=True, padding="max_length", max_length=max_len
        )

    def __len__(self) -> int:
        return len(self.labels)

    def __getitem__(self, i) -> dict:
        item = {k: torch.tensor(v[i]) for k, v in self.enc.items()}
        item["labels"] = torch.tensor(self.labels[i])
        return item
