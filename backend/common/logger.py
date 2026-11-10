"""日志配置（loguru）：trace_id 注入每条日志，控制台+文件双写，旧切片 zip 归档。"""

from __future__ import annotations

import sys
import time
import uuid6
import zipfile
from contextvars import ContextVar
from pathlib import Path
from typing import Any

from loguru import logger as _logger

# 本地计算 BASE_DIR，避免顶层 import backend.config 造成循环导入；
# setup_logging 内部惰性读取 config.logging。
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# 全链路 trace_id：由 TraceMiddleware / 认证依赖写入 contextvars，日志 patcher 读取。
trace_id_ctx: ContextVar[str | None] = ContextVar("trace_id", default=None)


def ensure_trace_id() -> str:
    """取当前上下文的 trace_id；没有就生成一个并写回 contextvars。

    写回是为了让同一次请求（同一 async 上下文）内后续日志复用同一个 id，
    而不是每条日志各生成一个。请求入口由 TraceIdMiddleware 优先透传
    X-Trace-Id，请求结束会 reset，不影响请求之间的隔离。
    """
    tid = trace_id_ctx.get()
    if not tid:
        tid = uuid6.uuid7().hex
        trace_id_ctx.set(tid)
    return tid


def _inject_trace_id(record: dict) -> None:
    """把 trace_id 注入日志 record。

    只读取当前上下文，不在日志阶段自动生成：服务启动、后台任务等没有 HTTP
    请求上下文的日志不应出现 trace；请求入口由 TraceIdMiddleware 写入。
    """
    tid = trace_id_ctx.get()
    record["extra"]["trace_id"] = tid
    record["extra"]["trace_prefix"] = f"trace={tid} | " if tid else ""


# loguru 为单例：附加包名前缀与 trace_id 注入两个 patcher
logger = _logger.patch(lambda r: r.update(name=f"{BASE_DIR.name}.{r['name']}")).patch(
    _inject_trace_id
)

# 字段取值来自 loguru record：
#   process.id   —— 进程 PID，区分多 worker 部署，也能看出日志是否跨重启
#   thread.name  —— 线程名（MainThread / asyncio_0 ...），用于判断同步阻塞落在了哪个线程
#   毫秒时间戳   —— 与 trace_id 一起对齐链路，秒级精度不够排并发问题
LOG_FORMAT = (
    "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | "
    "pid={process.id} thread={thread.name} | "
    "{extra[trace_prefix]}{name}:{file}:{line} - {message}"
)


def _log_path(file: str) -> Path:
    """把配置里的日志路径解析成绝对路径：相对路径以项目根目录为基准。

    这样 `LOG_FILE=logs/app.log` 恒定落到 <项目根>/logs/，不再随启动目录变化
    （从 backend/ 启动时曾落到 backend/logs/）。绝对路径原样使用。
    """
    p = Path(file).expanduser()
    return p if p.is_absolute() else (BASE_DIR / p)


def setup_logging(*, level: str | None = None) -> None:
    """配置日志（项目启动时调用一次）。控制台 + 文件双写，level 缺省用配置。"""
    from backend.config import config

    _logger.remove()
    lvl = level or config.logging.level
    _logger.add(sys.stderr, level=lvl, colorize=True, format=LOG_FORMAT)
    _logger.add(
        str(_log_path(config.logging.file)),
        level=lvl,
        rotation="00:00",  # 每天零点切片
        # 不在切片时立即压缩：近 N 天保留明文便于 tail/grep，更早的由 archive_old_logs 打包；
        # retention 留 N+7 天缓冲，避免后台归档还没来得及打包就被 loguru 删掉。
        retention=f"{config.logging.days + 7} days",
        enqueue=True,  # 异步写入，避免阻塞主逻辑
        encoding="utf-8",
        format=LOG_FORMAT,
    )


def archive_old_logs(*, days: int | None = None, log_file: str | None = None) -> list[Path]:
    """把超过 `days` 天的切片日志打包成 zip 并删除原文件。

    loguru 的 compression 会在每次切片时立即压缩，做不到「近 N 天保留明文、
    更早的再归档」。这里改为按文件 mtime 判定：切片日志在当天零点后不再写入，
    mtime 超过 N 天才打包，天然不会碰到正在写入的 app.log。

    返回本次新生成的 zip 路径列表；无文件需要归档时返回空列表。
    """
    from backend.config import config

    target = _log_path(log_file or config.logging.file)
    log_dir = target.parent
    archive_dir = log_dir / "archive"
    keep_days = config.logging.days if days is None else days
    cutoff = time.time() - keep_days * 86400
    created: list[Path] = []
    if not log_dir.is_dir():
        return created

    # 只归档按日期切出的 `app.*.log`，不碰当前正在写的 app.log，也不碰历史 zip。
    for f in sorted(log_dir.glob(f"{target.stem}.*{target.suffix}")):
        if not f.is_file() or f == target:
            continue
        if f.stat().st_mtime >= cutoff:
            continue
        archive_dir.mkdir(parents=True, exist_ok=True)
        zip_path = archive_dir / f"{f.stem}.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(f, arcname=f.name)
        f.unlink()
        created.append(zip_path)
    return created


def get_logger(name: str | None = None) -> Any:
    """获取 logger（loguru 为单例，name 仅语义）。

    必须返回打过 patch 的 logger：name 前缀与 trace 前缀注入都挂在它上面。
    若返回原始 _logger，LOG_FORMAT 里的 {extra[trace_prefix]} 会因 extra 为空而 KeyError。
    """
    return logger


def brief(value: Any, *, limit: int = 240) -> str:
    """把任意值压成单行摘要，供中间件客户端的 debug 日志使用。

    大对象（向量、缓存内容、批量结果）只保留类型与长度/前若干字符，
    避免单条日志刷屏，也避免把 session token 等敏感值整段落盘。
    """
    try:
        if value is None:
            return "None"
        if isinstance(value, (bytes, bytearray)):
            return f"<bytes len={len(value)}>"
        if isinstance(value, str):
            text = value
        elif isinstance(value, (list, tuple, set)):
            return f"<{type(value).__name__} len={len(value)}>"
        elif isinstance(value, dict):
            return f"<dict keys={list(value)[:8]}>"
        else:
            text = repr(value)
        text = text.replace("\n", "\\n").replace("\r", "\\r")
        return text if len(text) <= limit else f"{text[:limit]}...<len={len(text)}>"
    except Exception:  # noqa: BLE001 - 日志格式化绝不能影响业务
        return f"<unprintable {type(value).__name__}>"


def brief_args(args: Any, kwargs: Any, *, limit: int = 240) -> str:
    """命令/方法参数摘要：位置参数逐个压短，关键字参数保留键名。"""
    parts = [brief(a, limit=limit) for a in args]
    parts += [f"{k}={brief(v, limit=limit)}" for k, v in kwargs.items()]
    joined = ", ".join(parts)
    return joined if len(joined) <= 600 else f"{joined[:600]}...<len={len(joined)}>"


__all__ = [
    "logger",
    "setup_logging",
    "archive_old_logs",
    "get_logger",
    "brief",
    "brief_args",
    "ensure_trace_id",
    "trace_id_ctx",
    "LOG_FORMAT",
]
