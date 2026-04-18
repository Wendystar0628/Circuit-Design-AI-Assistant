"""PNG tEXt chunk injection (pure stdlib).

PyQt ``QPixmap.save`` writes standards-compliant PNG files but refuses
to attach custom textual metadata. Rather than pull in Pillow just for
that, this module rewrites a PNG file in place, inserting ``tEXt``
chunks right after the mandatory ``IHDR`` header.

Why this matters:
    Every simulation artifact we hand to the agent **must** declare
    which circuit (``file_name`` / ``file_path``) it came from. For
    JSON/TXT/CSV files we do that through textual headers; for PNG
    there is no other way to embed that without reaching outside the
    file.

Reference:
    PNG specification (ISO/IEC 15948) section 11.3.4.3 — tEXt chunk.
    Keywords are 1-79 bytes, ISO 8859-1, followed by 0x00 and the
    text value (unrestricted length, no terminator).
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path
from typing import Dict, Iterable, Mapping


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_IHDR_LENGTH_OFFSET = len(PNG_SIGNATURE)
_IHDR_CHUNK_HEADER_SIZE = 8  # length (4) + type (4)
_CHUNK_CRC_SIZE = 4


def inject_png_text_chunks(
    path: str | Path,
    chunks: Mapping[str, str],
) -> bool:
    """Insert ``tEXt`` chunks into an existing PNG file in place.

    Args:
        path: Path to an existing PNG file (produced by e.g.
            ``QPixmap.save``).
        chunks: Mapping of keyword → text. Empty mapping is a no-op.

    Returns:
        ``True`` if the file was rewritten with the new chunks,
        ``False`` if the file is missing / not a valid PNG.

    Raises:
        ValueError: If a keyword is invalid (empty, too long, or
            contains bytes that cannot be encoded as ISO 8859-1).
    """
    if not chunks:
        return True

    target = Path(path)
    if not target.is_file():
        return False

    data = target.read_bytes()
    if not data.startswith(PNG_SIGNATURE):
        return False

    encoded_chunks = b"".join(_build_text_chunk(key, value) for key, value in chunks.items())
    if not encoded_chunks:
        return True

    # Splice new chunks immediately after IHDR (first chunk after
    # signature). That keeps the file valid regardless of what other
    # chunks the PNG already contained.
    ihdr_len_field = data[_IHDR_LENGTH_OFFSET : _IHDR_LENGTH_OFFSET + 4]
    (ihdr_data_length,) = struct.unpack(">I", ihdr_len_field)
    ihdr_end_offset = (
        _IHDR_LENGTH_OFFSET
        + _IHDR_CHUNK_HEADER_SIZE
        + ihdr_data_length
        + _CHUNK_CRC_SIZE
    )

    new_bytes = data[:ihdr_end_offset] + encoded_chunks + data[ihdr_end_offset:]
    target.write_bytes(new_bytes)
    return True


def read_png_text_chunks(path: str | Path) -> Dict[str, str]:
    """Read all ``tEXt`` chunks from a PNG file. Utility for tests.

    Raises:
        ValueError: If the file is not a valid PNG.
    """
    data = Path(path).read_bytes()
    if not data.startswith(PNG_SIGNATURE):
        raise ValueError(f"Not a PNG file: {path}")

    offset = len(PNG_SIGNATURE)
    result: Dict[str, str] = {}
    while offset + _IHDR_CHUNK_HEADER_SIZE + _CHUNK_CRC_SIZE <= len(data):
        (length,) = struct.unpack(">I", data[offset : offset + 4])
        chunk_type = data[offset + 4 : offset + 8]
        chunk_data = data[offset + 8 : offset + 8 + length]
        offset += 8 + length + _CHUNK_CRC_SIZE
        if chunk_type == b"tEXt":
            sep_index = chunk_data.find(b"\x00")
            if sep_index == -1:
                continue
            keyword = chunk_data[:sep_index].decode("latin-1", errors="replace")
            value = chunk_data[sep_index + 1 :].decode("latin-1", errors="replace")
            result[keyword] = value
        if chunk_type == b"IEND":
            break
    return result


def _build_text_chunk(keyword: str, text: str) -> bytes:
    normalized_keyword = str(keyword or "").strip()
    if not normalized_keyword:
        raise ValueError("PNG tEXt keyword must be non-empty")
    if len(normalized_keyword) > 79:
        raise ValueError(f"PNG tEXt keyword too long (>{79}): {normalized_keyword!r}")

    try:
        keyword_bytes = normalized_keyword.encode("latin-1")
        text_bytes = (text or "").encode("latin-1", errors="replace")
    except UnicodeEncodeError as exc:
        raise ValueError(f"PNG tEXt value not encodable as ISO 8859-1: {exc}") from exc

    chunk_data = keyword_bytes + b"\x00" + text_bytes
    chunk_type = b"tEXt"
    length_bytes = struct.pack(">I", len(chunk_data))
    crc_bytes = struct.pack(">I", zlib.crc32(chunk_type + chunk_data) & 0xFFFFFFFF)
    return length_bytes + chunk_type + chunk_data + crc_bytes


__all__ = [
    "inject_png_text_chunks",
    "read_png_text_chunks",
]
