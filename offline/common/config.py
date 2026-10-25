"""
config - 离线模块配置（环境变量覆盖，默认指向项目内路径）。

路径默认相对于项目根（offline/ 的上级）。训练产物默认写入 models/...，
该目录已被 .gitignore 忽略，权重不入库；源码与示例数据入库。
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent.parent  # agent-platform/

# 将项目根 .env 载入环境变量（override=True：.env 覆盖已有环境变量）；from_env() 统一读 os.environ
load_dotenv(dotenv_path=ROOT / ".env", override=True)


@dataclass
class OfflineConfig:
    """离线训练/评估配置。"""

    data: Path = ROOT / "offline" / "sample_data" / "intents.jsonl"
    base_model: str = "bert-base-chinese"
    model_out: Path = ROOT / "models" / "bert-intent-recognition-model"
    epochs: int = 3
    batch: int = 16
    lr: float = 2e-5
    max_len: int = 64

    @classmethod
    def from_env(cls) -> "OfflineConfig":
        def env(key: str, default):
            v = os.environ.get(key)
            return v if v else default

        return cls(
            data=Path(env("OFFLINE_DATA", str(cls.data))),
            base_model=env("OFFLINE_BASE_MODEL", cls.base_model),
            model_out=Path(env("OFFLINE_MODEL_OUT", str(cls.model_out))),
            epochs=int(env("OFFLINE_EPOCHS", str(cls.epochs))),
            batch=int(env("OFFLINE_BATCH", str(cls.batch))),
            lr=float(env("OFFLINE_LR", str(cls.lr))),
            max_len=int(env("OFFLINE_MAX_LEN", str(cls.max_len))),
        )
