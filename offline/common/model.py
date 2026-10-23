"""
model - HF 格式意图分类器产物的构建/保存/加载。

产物目录结构：
  model.safetensors / pytorch_model.bin   HF 序列分类模型
  tokenizer.json / config.json            HF tokenizer + 模型配置
  meta.json                               {"labels": [...], "max_len": 64}  ← 在线侧据此映射

在线消费端（backend.core.llm_factory）仅读取 meta.json + 模型，不依赖本模块代码。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Tuple

import torch

from offline.common.intents import INTENT_LABELS


def build_model(base_model: str, num_labels: int):
    """构造序列分类模型。"""
    from transformers import AutoModelForSequenceClassification

    return AutoModelForSequenceClassification.from_pretrained(base_model, num_labels=num_labels)


def save_artifact(model, tokenizer, out_dir: Path, max_len: int = 64) -> None:
    """保存模型 + tokenizer + meta.json 到 out_dir。"""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(out_dir)
    tokenizer.save_pretrained(out_dir)
    meta = {"labels": INTENT_LABELS, "max_len": max_len}
    (out_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")


def load_artifact(out_dir: Path) -> Tuple[object, object, list, int]:
    """加载产物，返回 (model, tokenizer, labels, max_len)。"""
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    out_dir = Path(out_dir)
    meta = json.loads((out_dir / "meta.json").read_text(encoding="utf-8"))
    labels: list = meta["labels"]
    max_len: int = int(meta.get("max_len", 64))
    tokenizer = AutoTokenizer.from_pretrained(out_dir)
    model = AutoModelForSequenceClassification.from_pretrained(out_dir)
    model.eval()
    return model, tokenizer, labels, max_len
