"""文档加载：MinIO 字节解析 PDF/Markdown/TXT，全内存不落盘，按扩展名分发。"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from backend.common.logger import logger
from backend.rag.ranked import LoadedPage

# 编码候选集（参考项目 config.candidate_encodings，本项目不新增 settings 单例）
CANDIDATE_ENCODINGS: tuple[str, ...] = (
    "utf-8",
    "utf-8-sig",
    "gbk",
    "gb2312",
    "gb18030",
    "big5",
)

SUPPORTED_EXTS: tuple[str, ...] = (".pdf", ".md", ".txt")


def _content_hash(text: str) -> str:
    """内容 MD5 前 16 位，用作 document_id / 去重键。"""
    return hashlib.md5(text.encode("utf-8")).hexdigest()[:16]


def _decode(data: bytes, *, file_name: str) -> str:
    """按候选编码依次解码，全部失败则 UTF-8 忽略非法字节兜底。"""
    for enc in CANDIDATE_ENCODINGS:
        try:
            return data.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    logger.warning(f"rag.loader: 编码候选均失败，强制 utf-8 忽略模式 file={file_name}")
    return data.decode("utf-8", errors="ignore")


def _strip_front_matter(text: str) -> str:
    """去除 Markdown 开头的 YAML/TOML front matter。"""
    return re.sub(r"^---\s*\n(?:(?!---\s*\n).)*\n---\s*\n", "", text, flags=re.DOTALL)


def _load_pdf(data: bytes, *, file_name: str) -> list[LoadedPage]:
    import pymupdf

    from backend.config import config
    from backend.rag import ocr

    # 逐页降级：有文本层用文本；无文本层（扫描页/图片型）走 OCR
    ocr_enabled = bool(getattr(config.qa, "ocr_enabled", True)) and ocr.is_available()
    dpi = int(getattr(config.qa, "ocr_dpi", 180))
    max_ocr_pages = int(getattr(config.qa, "ocr_max_pages", 200))

    pages: list[LoadedPage] = []
    doc = pymupdf.open(stream=data, filetype="pdf")
    try:
        total = len(doc)
        texts: list[str] = []
        ocr_used = 0
        for page_no in range(total):
            text = doc[page_no].get_text()
            if not text.strip() and ocr_enabled and ocr_used < max_ocr_pages:
                try:
                    pix = doc[page_no].get_pixmap(dpi=dpi)
                    text = ocr.ocr_image(pix.tobytes("png")) or ""
                    ocr_used += 1
                    logger.debug(
                        f"OCR 页 {page_no + 1}/{total} chars={len(text)} file={file_name}"
                    )
                except Exception:  # noqa: BLE001 - 单页失败跳过
                    logger.exception(f"OCR 渲染失败 第 {page_no + 1} 页 file={file_name}")
                    text = ""
            texts.append(text)

        full_text = "\n\n".join(texts)
        file_hash = _content_hash(full_text)
        for page_no, text in enumerate(texts):
            if not text.strip():
                continue
            pages.append(
                LoadedPage(
                    content=text,
                    metadata={
                        "doc_type": "pdf",
                        "file_name": file_name,
                        "file_hash": file_hash,
                        "page_hash": _content_hash(text),
                        "page": page_no + 1,
                        "total_page_cnt": total,
                        "char_count": len(text),
                        "source_location": f"{file_name} > 第 {page_no + 1} 页",
                    },
                )
            )
    finally:
        doc.close()
    return pages


def _load_markdown(data: bytes, *, file_name: str) -> list[LoadedPage]:
    text = _strip_front_matter(_decode(data, file_name=file_name)).strip()
    if not text:
        return []
    return [
        LoadedPage(
            content=text,
            metadata={
                "doc_type": "md",
                "file_name": file_name,
                "file_hash": _content_hash(text),
                "char_count": len(text),
                "source_location": file_name,
            },
        )
    ]


def _load_text(data: bytes, *, file_name: str) -> list[LoadedPage]:
    text = _decode(data, file_name=file_name).strip()
    if not text:
        return []
    return [
        LoadedPage(
            content=text,
            metadata={
                "doc_type": "txt",
                "file_name": file_name,
                "file_hash": _content_hash(text),
                "char_count": len(text),
                "source_location": file_name,
            },
        )
    ]


_LOADERS: dict[str, Any] = {
    ".pdf": _load_pdf,
    ".md": _load_markdown,
    ".txt": _load_text,
}


def load_document(data: bytes, *, file_name: str, file_ext: str | None = None) -> list[LoadedPage]:
    """从字节加载文档；不支持的扩展名抛 ValueError（由上层回写 parse_status=failed）。"""
    ext = (file_ext or "").lower()
    if not ext:
        ext = "." + file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""
    loader = _LOADERS.get(ext)
    if loader is None:
        raise ValueError(f"不支持的文件类型 [{ext}]，当前支持 {SUPPORTED_EXTS}")
    pages = loader(data, file_name=file_name)
    logger.debug(f"rag.loader.done | file={file_name} ext={ext} pages={len(pages)}")
    return pages
