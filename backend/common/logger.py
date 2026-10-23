"""
logger - 日志配置（基于 loguru，对齐 RAG-Ultra）

全程 trace_id 注入每条日志（由中间件写入 contextvars，patcher 读取），便于按链路收集。
控制台 + 文件双写；文件按「日期 + 大小」切片、超期清理。get_logger 返回 loguru 单例。
"""
from __future__ import annotations

import re
import sys
from contextvars import ContextVar
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from loguru import logger as _logger

# 注意：不直接在模块顶层 import backend.config，避免 config.settings -> common.logger 的循环导入。
# 需要配置的函数（setup_logging）内部惰性导入。BASE_DIR 本地计算，保持与 backend.config 解耦。
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# 全链路 trace_id：由 TraceMiddleware / 认证依赖写入 contextvars，日志 patcher 读取。
trace_id_ctx: ContextVar[str | None] = ContextVar("trace_id", default=None)


def _inject_trace_id(record: dict) -> None:
    """把当前上下文 trace_id 注入日志 record（无则 '-'）。"""
    record["extra"]["trace_id"] = trace_id_ctx.get() or "-"


# loguru 为单例：附加包名前缀与 trace_id 注入两个 patcher
logger = (
    _logger
    .patch(lambda r: r.update(name=f"{BASE_DIR.name}.{r['name']}"))
    .patch(_inject_trace_id)
)

LOG_FORMAT = (
    "{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | trace={extra[trace_id]} | "
    "{name}:{file}:{line} - {message}"
)


class DatedSizeRotatingSink:
    """按「日期 + 大小」切片、文件名形如 app-YYYYMMDD-<index>.log 的文件写入器。"""

    _PATTERN = re.compile(r"^app-(\d{8})-.*\.log$")

    def __init__(self, log_dir: Path, max_bytes: int = 1024 ** 3, encoding: str = "utf-8",
                 retention_days: int = 7) -> None:
        self.log_dir = Path(log_dir)
        self.max_bytes = max_bytes
        self.encoding = encoding
        self.retention_days = retention_days
        self._date = ""
        self._index = 0
        self._file = None
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def _open(self) -> None:
        if self._file is not None:
            self._file.close()
        self._file = open(self.log_dir / f"app-{self._date}-{self._index}.log", "a", encoding=self.encoding)

    def _cleanup(self) -> None:
        if self.retention_days <= 0:
            return
        today = datetime.strptime(self._date, "%Y%m%d")
        cutoff = (today - timedelta(days=self.retention_days)).strftime("%Y%m%d")
        for p in self.log_dir.glob("app-*-*.log"):
            m = self._PATTERN.match(p.name)
            if m and m.group(1) < cutoff:
                try:
                    p.unlink()
                except OSError:
                    pass

    def __call__(self, message: Any) -> None:
        record = message.record
        day = record["time"].strftime("%Y%m%d")
        text = str(message)
        size = len(text.encode(self.encoding, errors="replace"))
        if day != self._date:
            self._date = day
            self._index = 0
            self._cleanup()
            self._open()
        elif self._file.tell() + size > self.max_bytes:
            self._index += 1
            self._open()
        self._file.write(text)
        self._file.flush()

    def stop(self) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None


def setup_logging(*, level: str | None = None) -> None:
    """配置日志（项目启动时调用一次）。控制台 + 文件双写，level 缺省用配置。"""
    from backend.config import config

    _logger.remove()
    lvl = level or config.logging.level
    _logger.add(sys.stderr, level=lvl, colorize=False, format=LOG_FORMAT)
    file_sink = DatedSizeRotatingSink(
        Path(config.logging.file).parent, max_bytes=config.logging.size,
        encoding="utf-8", retention_days=config.logging.days,
    )
    _logger.add(file_sink, level=lvl, enqueue=True, format=LOG_FORMAT)


def get_logger(name: str | None = None) -> Any:
    """获取 logger（loguru 为单例，name 仅语义）。"""
    return _logger


__all__ = ["logger", "setup_logging", "get_logger", "trace_id_ctx", "LOG_FORMAT"]
