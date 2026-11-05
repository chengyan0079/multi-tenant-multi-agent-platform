"""
train_pipeline.py - 离线意图识别模型训练与评估流水线

基于 all-MiniLM-L6-v2（BERT 架构蒸馏模型）微调文本分类头，用于离线训练
"意图识别"分类模型。训练数据为 JSONL 格式，每行一条：
    {"text": "问题文本", "label": "意图类别"}

标签集合从数据中动态构建，支持任意数量的意图类别（参考 thy-edu-agent 的同
模型、同数据范式：general / specialized 二分类，这里泛化为 N 分类）。

运行（依赖 torch / transformers / scikit-learn / numpy）：
    cd offline
    python train_pipeline.py
路径均可选覆盖：--base-model / --data / --output
"""
import argparse
import json
import logging
import os
from pathlib import Path

import numpy as np
import torch
from sklearn.metrics import classification_report, confusion_matrix
from sklearn.model_selection import train_test_split
from torch.utils.data import Dataset
from transformers import (
    BertForSequenceClassification,
    BertTokenizer,
    Trainer,
    TrainingArguments,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("train_intent_classifier")

# 离线脚本根目录（本文件所在目录）：offline/
OFFLINE_DIR = Path(__file__).resolve().parent
# 基座模型：agent-platform/models/all-MiniLM-L6-v2
DEFAULT_BASE_MODEL = OFFLINE_DIR.parent / "models" / "all-MiniLM-L6-v2"
# DEFAULT_DATA_FILE = OFFLINE_DIR / "data" / "training_data.jsonl"
DEFAULT_DATA_FILE = OFFLINE_DIR / "data" / "model_generic_1830.json"
DEFAULT_OUTPUT_DIR = OFFLINE_DIR / "models" / "classifier" / "intent_classifier"


class IntentDataset(Dataset):
    """自定义数据集：把 tokenizer 输出与标签封装为 Dataset。"""

    def __init__(self, inputs, labels):
        self.inputs = inputs
        self.labels = labels

    def __len__(self):
        return len(self.labels)

    def __getitem__(self, idx):
        item = {key: val[idx] for key, val in self.inputs.items()}
        item["labels"] = torch.tensor(self.labels[idx], dtype=torch.int64)
        return item


def _evaluate(model, inputs, labels, target_names):
    dataset = IntentDataset(inputs, labels)
    trainer = Trainer(model=model)
    predictions = trainer.predict(dataset)
    pred_labels = np.argmax(predictions.predictions, axis=-1)

    logger.info(f"混淆矩阵:\n{confusion_matrix(labels, pred_labels)}")
    if target_names:
        logger.info(
            "分类报告:\n"
            + classification_report(
                labels, pred_labels, target_names=target_names, zero_division=0
            )
        )


class QueryClassifierTrainer:
    """离线模型训练器：基于 MiniLM 微调序列分类头。"""

    def __init__(self, base_model_dir: str, model_output_dir: str):
        self.base_model_dir = base_model_dir
        self.model_output_dir = model_output_dir
        self.tokenizer = BertTokenizer.from_pretrained(base_model_dir)
        self.label_to_idx: dict[str, int] = {}

    def _load_data(self, data_file: str):
        if not os.path.exists(data_file):
            raise FileNotFoundError(f"数据集文件不存在: {data_file}")

        with open(data_file, encoding="utf-8") as f:
            data = [json.loads(line) for line in f if line.strip()]

        if not data:
            raise ValueError("数据集为空")

        # 动态构建标签映射，支持任意数量的意图类别（按标签名排序保证可复现）
        labels_set = sorted({item["label"] for item in data})
        self.label_to_idx = {label: idx for idx, label in enumerate(labels_set)}
        logger.info(f"发现 {len(self.label_to_idx)} 个意图类别: {self.label_to_idx}")

        if len(self.label_to_idx) < 2:
            logger.warning(
                "仅检测到 1 个意图类别，分类器无法学习区分性特征；"
                "请补充其他类别样本（如 specialized）后再训练。"
            )

        texts = [item["query"] for item in data]
        labels = [self.label_to_idx[item["label"]] for item in data]
        return texts, labels

    def train(self, data_file: str):
        """执行训练与评估主流程"""
        texts, labels = self._load_data(data_file)
        num_labels = len(self.label_to_idx)
        target_names = [label for label, _ in sorted(self.label_to_idx.items(), key=lambda x: x[1])]

        train_texts, valid_texts, train_labels, valid_labels = train_test_split(
            texts, labels, test_size=0.2, random_state=42, stratify=labels
        )

        params = {
            "truncation": True,
            "padding": True,
            "max_length": 128,
            "return_tensors": "pt",
        }
        train_inputs = self.tokenizer(train_texts, **params)
        valid_inputs = self.tokenizer(valid_texts, **params)
        train_dataset = IntentDataset(train_inputs, train_labels)
        valid_dataset = IntentDataset(valid_inputs, valid_labels)

        model = BertForSequenceClassification.from_pretrained(
            self.base_model_dir, num_labels=num_labels
        )

        use_cuda = torch.cuda.is_available()
        training_args = TrainingArguments(
            output_dir=str(OFFLINE_DIR / ".bert_ft_train_results"),  # 训练过程检查点落盘路径
            num_train_epochs=4,                  # 训练轮次
            per_device_train_batch_size=16,      # 单设备训练批次大小
            per_device_eval_batch_size=16,       # 单设备评估批次大小
            warmup_steps=32,                     # 学习率预热步数
            weight_decay=0.01,                   # 权重衰减（L2 正则化系数）
            logging_steps=8,                      # 日志记录频率
            eval_strategy="epoch",               # 每个 Epoch 之后运行评估（旧版 transformers 用 evaluation_strategy）
            save_strategy="epoch",               # 每个 Epoch 之后保存检查点
            load_best_model_at_end=True,         # 训练结束时加载最佳模型
            save_total_limit=1,                  # 检查点保留上限
            metric_for_best_model="eval_loss",   # 评判最佳模型的指标
            fp16=use_cuda,                       # 有 GPU 时启用半精度
            dataloader_pin_memory=use_cuda,
        )
        trainer = Trainer(
            model=model,
            args=training_args,
            train_dataset=train_dataset,
            eval_dataset=valid_dataset,
            compute_metrics=lambda p: {
                "accuracy": (np.argmax(p.predictions, axis=-1) == p.label_ids).mean()
            },
        )

        logger.info("开始训练意图分类模型...")
        trainer.train()

        # 保存微调后的模型与分词器
        os.makedirs(self.model_output_dir, exist_ok=True)
        model.save_pretrained(self.model_output_dir)
        self.tokenizer.save_pretrained(self.model_output_dir)
        # 导出标签映射，便于推理时对齐
        with open(
            os.path.join(self.model_output_dir, "label_mapping.json"),
            "w",
            encoding="utf-8",
        ) as f:
            json.dump(self.label_to_idx, f, ensure_ascii=False, indent=2)
        logger.info(f"模型已成功导出至: {self.model_output_dir}")

        # 用验证数据进行模型评估
        _evaluate(model, valid_inputs, valid_labels, target_names)


def main():
    parser = argparse.ArgumentParser(description="离线训练意图识别分类模型")
    parser.add_argument("--base-model", default=str(DEFAULT_BASE_MODEL), help="基座模型目录")
    parser.add_argument("--data", default=str(DEFAULT_DATA_FILE), help="训练数据 JSONL 路径")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_DIR), help="微调后模型输出目录")
    args = parser.parse_args()

    trainer = QueryClassifierTrainer(
        base_model_dir=args.base_model,
        model_output_dir=args.output,
    )
    trainer.train(args.data)


if __name__ == "__main__":
    main()
