# File Extractor - Unified File Content Extraction for RAG Indexing
"""
统一文件内容提取器

职责：
- 维护所有可索引的文件类型注册表
- 为每种文件类型提供对应的内容提取策略
- 向 RAGManager 提供统一的 extract_content(abs_path) 入口

支持的文件类型：
  电路/仿真：.cir .sp .spice .lib .inc .sub .net
  代码：      .py .js .ts .jsx .tsx .java .c .cpp .h .hpp .cs .go .rs .rb .sh .m
  文本/文档： .md .txt .rst .csv
  配置：      .yaml .yml .toml .ini .cfg .conf .json .xml .html
  富文本：    .pdf .docx

依赖（已在 requirements.txt）：
  PyMuPDF>=1.23.0  → PDF 提取（import fitz）
  python-docx>=1.1.0 → DOCX 提取
"""

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Optional, Set

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FileIndexRule:
    extension: str
    should_index: bool
    max_size: int
    exclude_reason: str = ""

# ============================================================
# 文件大小上限（按类型）
# ============================================================

_MAX_SIZE_TEXT = 1 * 1024 * 1024    # 1 MB  —— 代码 / 文本
_MAX_SIZE_PDF  = 20 * 1024 * 1024   # 20 MB —— PDF
_MAX_SIZE_DOCX = 10 * 1024 * 1024   # 10 MB —— DOCX

# ============================================================
# 可索引扩展名 → 最大文件大小
# ============================================================

INDEXABLE_EXTENSIONS: Dict[str, int] = {
    # 电路 / 仿真
    ".cir":   _MAX_SIZE_TEXT,
    ".sp":    _MAX_SIZE_TEXT,
    ".spice": _MAX_SIZE_TEXT,
    ".lib":   _MAX_SIZE_TEXT,
    ".inc":   _MAX_SIZE_TEXT,
    ".sub":   _MAX_SIZE_TEXT,
    ".net":   _MAX_SIZE_TEXT,
    # Python / Web / 通用脚本
    ".py":    _MAX_SIZE_TEXT,
    ".js":    _MAX_SIZE_TEXT,
    ".ts":    _MAX_SIZE_TEXT,
    ".jsx":   _MAX_SIZE_TEXT,
    ".tsx":   _MAX_SIZE_TEXT,
    ".sh":    _MAX_SIZE_TEXT,
    ".bash":  _MAX_SIZE_TEXT,
    # 系统/嵌入式
    ".c":     _MAX_SIZE_TEXT,
    ".cpp":   _MAX_SIZE_TEXT,
    ".h":     _MAX_SIZE_TEXT,
    ".hpp":   _MAX_SIZE_TEXT,
    ".m":     _MAX_SIZE_TEXT,
    # JVM / CLR
    ".java":  _MAX_SIZE_TEXT,
    ".cs":    _MAX_SIZE_TEXT,
    ".go":    _MAX_SIZE_TEXT,
    ".rs":    _MAX_SIZE_TEXT,
    ".rb":    _MAX_SIZE_TEXT,
    # 文档
    ".md":    _MAX_SIZE_TEXT,
    ".txt":   _MAX_SIZE_TEXT,
    ".rst":   _MAX_SIZE_TEXT,
    # 配置 / 数据
    ".yaml":  _MAX_SIZE_TEXT,
    ".yml":   _MAX_SIZE_TEXT,
    ".toml":  _MAX_SIZE_TEXT,
    ".ini":   _MAX_SIZE_TEXT,
    ".cfg":   _MAX_SIZE_TEXT,
    ".conf":  _MAX_SIZE_TEXT,
    ".json":  _MAX_SIZE_TEXT,
    ".xml":   _MAX_SIZE_TEXT,
    ".html":  _MAX_SIZE_TEXT,
    # 富文档
    ".pdf":   _MAX_SIZE_PDF,
    ".docx":  _MAX_SIZE_DOCX,
}

ATTACHMENT_TEXT_EXTENSIONS: Dict[str, int] = {
    **INDEXABLE_EXTENSIONS,
    ".csv": _MAX_SIZE_TEXT,
}

ATTACHMENT_IMAGE_EXTENSIONS: Set[str] = {
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
}

EXCLUDED_INDEX_RULES: Dict[str, FileIndexRule] = {
    ".csv": FileIndexRule(
        extension=".csv",
        should_index=False,
        max_size=_MAX_SIZE_TEXT,
        exclude_reason="CSV 表格/数值数据文件已排除索引",
    ),
}


# ============================================================
# 内容提取器
# ============================================================

def _extract_pdf(abs_path: str, max_size: int) -> str:
    """使用 PyMuPDF 提取 PDF 文本"""
    try:
        import fitz  # PyMuPDF
        pages = []
        with fitz.open(abs_path) as doc:
            for page in doc:
                text = page.get_text("text")
                if text:
                    pages.append(text.strip())
        content = "\n\n".join(pages)
        # 超出字符限制时截断（max_size 字节 ≈ max_size 字符）
        if len(content) > max_size:
            logger.warning(
                f"PDF content truncated: {abs_path} "
                f"({len(content)} chars → {max_size})"
            )
            content = content[:max_size]
        return content
    except ImportError:
        logger.error("PyMuPDF (fitz) not installed. Install with: pip install PyMuPDF")
        return ""
    except Exception as e:
        logger.warning(f"PDF extraction failed for {abs_path}: {e}")
        return ""


def _extract_docx(abs_path: str, max_size: int) -> str:
    """使用 python-docx 提取 DOCX 文本"""
    try:
        from docx import Document
        doc = Document(abs_path)
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        content = "\n".join(paragraphs)
        if len(content) > max_size:
            content = content[:max_size]
        return content
    except ImportError:
        logger.error("python-docx not installed. Install with: pip install python-docx")
        return ""
    except Exception as e:
        logger.warning(f"DOCX extraction failed for {abs_path}: {e}")
        return ""


def _extract_text(abs_path: str, max_size: int) -> str:
    """通用文本文件提取（UTF-8，errors=replace）"""
    try:
        size = os.path.getsize(abs_path)
        if size > max_size:
            logger.warning(
                f"File too large, skipping: {abs_path} ({size} bytes > {max_size})"
            )
            return ""
        with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception as e:
        logger.warning(f"Failed to read file {abs_path}: {e}")
        return ""


# 扩展名 → 提取函数映射
_EXTRACTOR_MAP: Dict[str, Callable[[str, int], str]] = {
    ".pdf":  _extract_pdf,
    ".docx": _extract_docx,
}
# 其余扩展名全部走 _extract_text（默认）


# ============================================================
# 统一入口
# ============================================================

def extract_indexable_content(abs_path: str) -> str:
    """
    提取文件内容，供 RAGManager 索引使用。

    根据文件扩展名自动选择提取策略：
    - .pdf  → PyMuPDF 逐页提取
    - .docx → python-docx 段落提取
    - 其余  → UTF-8 文本读取

    Args:
        abs_path: 文件绝对路径

    Returns:
        提取到的纯文本内容；提取失败时返回空字符串
    """
    rule = get_file_index_rule(abs_path)
    if rule is None or not rule.should_index:
        return ""

    return _extract_by_extension(abs_path, rule.extension, rule.max_size)


def extract_attachment_text(abs_path: str) -> str:
    ext = Path(abs_path).suffix.lower()
    max_size = ATTACHMENT_TEXT_EXTENSIONS.get(ext)
    if max_size is None:
        return ""

    return _extract_by_extension(abs_path, ext, max_size)


def is_image_attachment_path(path: str, mime_type: str = "") -> bool:
    if isinstance(mime_type, str) and mime_type.lower().startswith("image/"):
        return True
    ext = Path(path).suffix.lower()
    return ext in ATTACHMENT_IMAGE_EXTENSIONS


def resolve_attachment_type(path: str, mime_type: str = "") -> str:
    if is_image_attachment_path(path, mime_type):
        return "image"
    return "file"


def _extract_by_extension(abs_path: str, extension: str, max_size: int) -> str:
    extractor = _EXTRACTOR_MAP.get(extension, _extract_text)
    return extractor(abs_path, max_size)


def get_file_index_rule(abs_path: str) -> Optional[FileIndexRule]:
    ext = Path(abs_path).suffix.lower()
    if ext in INDEXABLE_EXTENSIONS:
        return FileIndexRule(
            extension=ext,
            should_index=True,
            max_size=INDEXABLE_EXTENSIONS[ext],
        )

    return EXCLUDED_INDEX_RULES.get(ext)


__all__ = [
    "ATTACHMENT_IMAGE_EXTENSIONS",
    "ATTACHMENT_TEXT_EXTENSIONS",
    "FileIndexRule",
    "extract_attachment_text",
    "extract_indexable_content",
    "get_file_index_rule",
    "is_image_attachment_path",
    "resolve_attachment_type",
]
