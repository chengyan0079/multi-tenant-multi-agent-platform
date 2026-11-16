"""扫描件 OCR：RapidOCR（onnxruntime）懒加载单例，把单页图片转成文本。

用于「PDF 某页无文本层」（扫描件/图片型）时的逐页降级：
- 引擎懒加载（首次约 1~2s），之后复用；
- CPU 推理，调用方需放在线程里（避免阻塞事件循环）；
- 识别失败返回空串（该页跳过），不影响整篇解析。
"""

from __future__ import annotations

import threading

from backend.common.logger import logger

_engine = None
_lock = threading.Lock()


def is_available() -> bool:
    """是否安装了 rapidocr_onnxruntime（未装则整篇无文本时照常失败）。"""
    try:
        import rapidocr_onnxruntime  # noqa: F401

        return True
    except Exception:  # noqa: BLE001
        return False


def _get_engine():
    global _engine
    if _engine is None:
        with _lock:
            if _engine is None:
                from rapidocr_onnxruntime import RapidOCR

                _engine = RapidOCR()
                logger.info("RapidOCR 引擎已加载（扫描件 OCR 可用）")
    return _engine


async def preload() -> bool:
    """启动期预加载 OCR 引擎（放到线程里，避免阻塞事件循环）。

    返回是否成功；失败不抛（调用方降级为「首次使用时再懒加载」）。
    """
    import asyncio

    if not is_available():
        return False
    try:
        await asyncio.to_thread(_get_engine)
        return True
    except Exception:  # noqa: BLE001 - 预加载失败不阻断启动
        logger.exception("OCR 引擎预加载失败（首次解析时会重试懒加载）")
        return False


def ocr_image(png: bytes) -> str:
    """对单页 PNG 做 OCR，返回纯文本；失败返回空串。"""
    if not png:
        return ""
    try:
        engine = _get_engine()
        result, _elapsed = engine(png)
        if not result:
            return ""
        # RapidOCR 返回 [[box, text, score], ...]
        parts = [str(item[1]) for item in result if len(item) >= 2 and item[1]]
        return "\n".join(parts).strip()
    except Exception:  # noqa: BLE001 - 单页失败不影响整篇
        logger.exception("OCR 识别失败（该页跳过）")
        return ""
