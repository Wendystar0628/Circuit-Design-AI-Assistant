# Chunker - File Content Splitting for Vector Indexing
"""
文件内容分块器

将 file_extractor 提取的纯文本按文件类型拆分为适合向量检索的 chunk 列表。

分块策略：
  代码文件    → 结构感知（按顶层函数/类边界切分）
  电路文件    → 子电路边界（.subckt/.ends）
  Markdown/文本 → 段落感知（双换行 + 标题边界）
  PDF/DOCX   → 段落感知（同 Markdown，页/段已由 extractor 拆分）
  配置/数据   → 固定大小滑动窗口
"""

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

# ============================================================
# 数据类
# ============================================================

@dataclass
class Chunk:
    """单个文本块，携带向量数据库所需的元数据"""
    content: str
    chunk_id: str
    file_path: str
    chunk_index: int
    file_type: str
    start_char: int
    end_char: int
    symbol_name: str = ""


# ============================================================
# 文件类型分组
# ============================================================

CODE_EXTENSIONS = {
    ".py", ".js", ".ts", ".jsx", ".tsx",
    ".java", ".c", ".cpp", ".h", ".hpp",
    ".cs", ".go", ".rs", ".rb", ".sh", ".bash", ".m",
}

CIRCUIT_EXTENSIONS = {
    ".cir", ".sp", ".spice", ".sub", ".lib", ".inc", ".net",
}

DOC_EXTENSIONS = {
    ".md", ".txt", ".rst", ".csv", ".docx",
}

# PDF 和其他富文档/配置文件走固定窗口或段落（在 chunk_file 末尾 else 分支）

# ============================================================
# 大小限制
# ============================================================

MAX_CHARS_CODE    = 3000
MAX_CHARS_DOC     = 1500
MAX_CHARS_CONFIG  = 2000
OVERLAP_CHARS     = 200


# ============================================================
# 内部工具函数
# ============================================================

def _make_chunk_id(file_path: str, chunk_index: int) -> str:
    path_hash = hashlib.md5(file_path.encode("utf-8")).hexdigest()[:12]
    return f"{path_hash}_{chunk_index}"


def _split_fixed(
    content: str, max_chars: int, overlap: int
) -> List[Tuple[int, int]]:
    """返回 (start_char, end_char) 列表，按固定大小滑动窗口切分"""
    positions = []
    start = 0
    while start < len(content):
        end = min(start + max_chars, len(content))
        positions.append((start, end))
        if end == len(content):
            break
        start = end - overlap
    return positions


def _build_chunk(
    text: str,
    file_path: str,
    chunk_index: int,
    file_type: str,
    start_char: int = 0,
    end_char: int = 0,
    symbol_name: str = "",
) -> Chunk:
    return Chunk(
        content=text,
        chunk_id=_make_chunk_id(file_path, chunk_index),
        file_path=file_path,
        chunk_index=chunk_index,
        file_type=file_type,
        start_char=start_char,
        end_char=end_char or len(text),
        symbol_name=symbol_name,
    )


# ============================================================
# 策略：代码文件
# ============================================================

_CODE_TOP_LEVEL = {
    ".py":              re.compile(r"^(def |class )"),
    ".js":              re.compile(r"^(function |class |const |let |var |export )"),
    ".ts":              re.compile(r"^(function |class |const |let |var |export |interface |type )"),
    ".jsx":             re.compile(r"^(function |class |const |let |var |export )"),
    ".tsx":             re.compile(r"^(function |class |const |let |var |export |interface |type )"),
    ".java":            re.compile(r"^(public |private |protected |class |interface |enum )"),
    ".cs":              re.compile(r"^(public |private |protected |internal |class |interface |enum |struct )"),
    ".go":              re.compile(r"^(func |type |var |const )"),
    ".rs":              re.compile(r"^(pub |fn |struct |enum |impl |trait |type )"),
    ".rb":              re.compile(r"^(def |class |module )"),
    ".c":               re.compile(r"^[a-zA-Z_][a-zA-Z0-9_\s\*]+\s*\("),
    ".cpp":             re.compile(r"^[a-zA-Z_][a-zA-Z0-9_\s\*:<>]+\s*\("),
    ".h":               re.compile(r"^[a-zA-Z_][a-zA-Z0-9_\s\*]+\s*\("),
    ".hpp":             re.compile(r"^[a-zA-Z_][a-zA-Z0-9_\s\*:<>]+\s*\("),
}
_CODE_DEFAULT_PATTERN = re.compile(r"^(def |function |class |func )")

_SYMBOL_EXTRACT = re.compile(
    r"^(?:pub\s+)?(?:async\s+)?(?:def |class |function |func |fn |type |impl |trait |interface |enum |struct )(\w+)"
)


def _chunk_code(content: str, file_path: str, ext: str) -> List[Chunk]:
    lines = content.split("\n")
    pattern = _CODE_TOP_LEVEL.get(ext, _CODE_DEFAULT_PATTERN)

    boundaries = [0]
    symbol_names = ["<header>"]

    for i, line in enumerate(lines[1:], start=1):
        if pattern.match(line):
            boundaries.append(i)
            m = _SYMBOL_EXTRACT.match(line.strip())
            symbol_names.append(m.group(1) if m else line.strip()[:40])

    boundaries.append(len(lines))

    chunks: List[Chunk] = []
    idx = 0

    char_offsets = []
    pos = 0
    for line in lines:
        char_offsets.append(pos)
        pos += len(line) + 1  # +1 for \n

    for i in range(len(boundaries) - 1):
        start_line = boundaries[i]
        end_line   = boundaries[i + 1]
        text = "\n".join(lines[start_line:end_line]).strip()
        if not text:
            continue

        sym = symbol_names[i] if i < len(symbol_names) else ""
        start_c = char_offsets[start_line] if start_line < len(char_offsets) else 0
        end_c   = char_offsets[end_line - 1] + len(lines[end_line - 1]) if end_line > 0 else len(text)

        if len(text) > MAX_CHARS_CODE:
            for sc, ec in _split_fixed(text, MAX_CHARS_CODE, OVERLAP_CHARS):
                sub = text[sc:ec].strip()
                if sub:
                    chunks.append(_build_chunk(sub, file_path, idx, ext, sc, ec, sym))
                    idx += 1
        else:
            chunks.append(_build_chunk(text, file_path, idx, ext, start_c, end_c, sym))
            idx += 1

    return chunks


# ============================================================
# 策略：电路仿真文件
# ============================================================

def _chunk_circuit(content: str, file_path: str, ext: str) -> List[Chunk]:
    lines = content.split("\n")
    subckt_starts: List[int] = []
    subckt_ends:   List[int] = []
    subckt_names:  List[str] = []

    for i, line in enumerate(lines):
        stripped = line.strip().lower()
        if stripped.startswith(".subckt"):
            subckt_starts.append(i)
            parts = line.split()
            subckt_names.append(parts[1] if len(parts) > 1 else f"subckt_{i}")
        elif stripped.startswith(".ends"):
            subckt_ends.append(i)

    chunks: List[Chunk] = []
    idx = 0

    if subckt_starts and len(subckt_starts) == len(subckt_ends):
        prev_end = 0
        for j, (s, e) in enumerate(zip(subckt_starts, subckt_ends)):
            if j == 0 and s > 0:
                header = "\n".join(lines[:s]).strip()
                if header:
                    chunks.append(_build_chunk(header, file_path, idx, ext, symbol_name="<header>"))
                    idx += 1
            text = "\n".join(lines[s : e + 1]).strip()
            if text:
                chunks.append(_build_chunk(text, file_path, idx, ext, symbol_name=subckt_names[j]))
                idx += 1
            prev_end = e

        if prev_end < len(lines) - 1:
            tail = "\n".join(lines[prev_end + 1 :]).strip()
            if tail:
                chunks.append(_build_chunk(tail, file_path, idx, ext, symbol_name="<tail>"))
    else:
        line_block = 500
        for start_l in range(0, len(lines), line_block - 50):
            text = "\n".join(lines[start_l : start_l + line_block]).strip()
            if text:
                chunks.append(_build_chunk(text, file_path, idx, ext))
                idx += 1

    return chunks


# ============================================================
# 策略：文档文件（Markdown / 纯文本 / CSV / DOCX）
# ============================================================

def _chunk_document(content: str, file_path: str, ext: str) -> List[Chunk]:
    if ext == ".md":
        raw_parts = re.split(r"\n\n+", content)
    else:
        raw_parts = re.split(r"\n\n+", content)

    chunks: List[Chunk] = []
    idx = 0
    current: List[str] = []
    current_len = 0

    for part in raw_parts:
        part = part.strip()
        if not part:
            continue

        is_md_header = (ext == ".md") and bool(re.match(r"^#{1,3} ", part))
        part_len = len(part)

        force_flush = (current_len + part_len > MAX_CHARS_DOC and current) or (is_md_header and current)
        if force_flush:
            text = "\n\n".join(current).strip()
            if text:
                chunks.append(_build_chunk(text, file_path, idx, ext))
                idx += 1
            # 重叠：非标题时保留最后一段
            current = ([current[-1], part] if (not is_md_header and current) else [part])
            current_len = sum(len(p) for p in current)
        else:
            current.append(part)
            current_len += part_len

    if current:
        text = "\n\n".join(current).strip()
        if text:
            chunks.append(_build_chunk(text, file_path, idx, ext))

    return chunks


# ============================================================
# 策略：固定窗口（PDF / 配置 / 数据文件）
# ============================================================

def _chunk_fixed_window(content: str, file_path: str, ext: str) -> List[Chunk]:
    chunks: List[Chunk] = []
    for i, (sc, ec) in enumerate(_split_fixed(content, MAX_CHARS_CONFIG, OVERLAP_CHARS)):
        text = content[sc:ec].strip()
        if text:
            chunks.append(_build_chunk(text, file_path, i, ext, sc, ec))
    return chunks


# ============================================================
# 统一入口
# ============================================================

def chunk_file(content: str, file_path: str) -> List[Chunk]:
    """
    将文件纯文本内容拆分为 chunk 列表。

    Args:
        content:   file_extractor.extract_content() 返回的纯文本
        file_path: 相对路径（用于生成 chunk_id 和元数据）

    Returns:
        List[Chunk]，可直接送入 Embedder.embed_texts()
    """
    if not content or not content.strip():
        return []

    ext = Path(file_path).suffix.lower()

    if ext in CODE_EXTENSIONS:
        return _chunk_code(content, file_path, ext)
    if ext in CIRCUIT_EXTENSIONS:
        return _chunk_circuit(content, file_path, ext)
    if ext in DOC_EXTENSIONS:
        return _chunk_document(content, file_path, ext)
    return _chunk_fixed_window(content, file_path, ext)


__all__ = ["Chunk", "chunk_file"]
