"""gunicorn 配置：多 uvicorn worker（配合 Redis 分布式锁保证建表/迁移只跑一次）。"""
import os
from pathlib import Path

from dotenv import load_dotenv

# 将项目根 .env 载入环境变量（override=True：.env 覆盖已有环境变量），下方 os.getenv 统一读取
load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent / ".env", override=True)

bind = "0.0.0.0:8000"
workers = int(os.getenv("GUNICORN_WORKERS", "4"))
worker_class = "uvicorn.workers.UvicornWorker"
timeout = 120
graceful_timeout = 30
# 注意：main.py 自行管理 AppServer 生命周期；生产用 gunicorn 时改用 backend.main:app 入口按需调整
