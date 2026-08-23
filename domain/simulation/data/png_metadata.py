"""Safe PNG iTXt metadata injection (pure stdlib).

Rather than pull in an image framework solely to attach textual metadata,
this module rewrites a PNG file in place and inserts ``iTXt`` chunks directly
after the mandatory ``IHDR`` header.

Generated chart and waveform attachments carry their circuit identity inside
the PNG itself, just as manual text/CSV/JSON exports carry linkage headers.

Reference:
    PNG specification (ISO/IEC 15948) international textual ancillary chunks.
    This module has one protocol: uncompressed iTXt with UTF-8 values.
"""

from __future__ import annotations

import struct
import os
import tempfile
import zlib
from pathlib import Path
from typing import Dict, List, Mapping, Tuple


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_IHDR_CHUNK_HEADER_SIZE = 8  # length (4) + type (4)
_CHUNK_CRC_SIZE = 4
_MAX_TEXT_BYTES = 1_048_576


def inject_png_itxt_chunks(
    path: str | Path,
    chunks: Mapping[str, str],
) -> bool:
    """Replace iTXt chunks in an existing PNG file atomically.

    Args:
        path: Path to an existing PNG file (produced by e.g.
            ``QPixmap.save``).
        chunks: Mapping of keyword → text. Empty mapping is a no-op.

    Returns:
        ``True`` if the file was rewritten with the new chunks,
        ``False`` if the file is missing / not a valid PNG.

    Raises:
        ValueError: If a keyword is invalid (empty, too long, or not
            representable as ISO 8859-1 as required by PNG).
    """
    if not chunks:
        return True

    target = Path(path)
    if not target.is_file():
        return False

    data = target.read_bytes()
    try:
        parsed = _parse_png_chunks(data)
    except ValueError:
        return False

    normalized = {_normalize_keyword(key): str(value or "") for key, value in chunks.items()}
    encoded_chunks = b"".join(
        _build_itxt_chunk(key, value) for key, value in normalized.items()
    )
    if not encoded_chunks:
        return True

    # A keyword has one authoritative value.  Remove an existing current-
    # protocol chunk before inserting its replacement.
    output = bytearray(PNG_SIGNATURE)
    inserted = False
    for chunk_type, chunk_data, raw_chunk in parsed:
        if chunk_type == b"iTXt":
            existing_keyword = _extract_itxt_keyword(chunk_data)
            if existing_keyword in normalized:
                continue
        output.extend(raw_chunk)
        if chunk_type == b"IHDR" and not inserted:
            output.extend(encoded_chunks)
            inserted = True
    _atomic_write_bytes(target, bytes(output))
    return True


def read_png_itxt_chunks(path: str | Path) -> Dict[str, str]:
    """Read all current-protocol uncompressed ``iTXt`` chunks from a PNG.

    Raises:
        ValueError: If the file is not a valid PNG.
    """
    data = Path(path).read_bytes()
    parsed = _parse_png_chunks(data)
    result: Dict[str, str] = {}
    for chunk_type, chunk_data, _raw_chunk in parsed:
        if chunk_type == b"iTXt":
            decoded = _decode_itxt(chunk_data)
            if decoded is not None:
                keyword, value = decoded
                result[keyword] = value
    return result


def _normalize_keyword(keyword: str) -> str:
    normalized_keyword = str(keyword or "").strip()
    if not normalized_keyword:
        raise ValueError("PNG iTXt keyword must be non-empty")
    try:
        keyword_bytes = normalized_keyword.encode("latin-1")
    except UnicodeEncodeError as exc:
        raise ValueError(f"PNG text keyword is not encodable as ISO 8859-1: {exc}") from exc
    if not 1 <= len(keyword_bytes) <= 79:
        raise ValueError(f"PNG text keyword must be 1-79 bytes: {normalized_keyword!r}")
    if b"\x00" in keyword_bytes:
        raise ValueError("PNG text keyword cannot contain NUL")
    return normalized_keyword


def _build_itxt_chunk(keyword: str, text: str) -> bytes:
    keyword_bytes = _normalize_keyword(keyword).encode("latin-1")
    # iTXt carries UTF-8 values losslessly while keeping the standardized
    # Latin-1 keyword field.
    text_bytes = str(text or "").encode("utf-8")
    if len(text_bytes) > _MAX_TEXT_BYTES:
        raise ValueError("PNG text value exceeds 1 MiB safety limit")
    chunk_data = keyword_bytes + b"\x00\x00\x00\x00\x00" + text_bytes
    chunk_type = b"iTXt"
    length_bytes = struct.pack(">I", len(chunk_data))
    crc_bytes = struct.pack(">I", zlib.crc32(chunk_type + chunk_data) & 0xFFFFFFFF)
    return length_bytes + chunk_type + chunk_data + crc_bytes


def _parse_png_chunks(data: bytes) -> List[Tuple[bytes, bytes, bytes]]:
    if not data.startswith(PNG_SIGNATURE):
        raise ValueError("Not a PNG file")
    offset = len(PNG_SIGNATURE)
    parsed: List[Tuple[bytes, bytes, bytes]] = []
    saw_iend = False
    while offset < len(data):
        if offset + _IHDR_CHUNK_HEADER_SIZE + _CHUNK_CRC_SIZE > len(data):
            raise ValueError("Truncated PNG chunk header")
        start = offset
        (length,) = struct.unpack(">I", data[offset : offset + 4])
        end = offset + _IHDR_CHUNK_HEADER_SIZE + length + _CHUNK_CRC_SIZE
        if end > len(data):
            raise ValueError("Truncated PNG chunk data")
        chunk_type = data[offset + 4 : offset + 8]
        chunk_data = data[offset + 8 : offset + 8 + length]
        expected_crc = struct.unpack(">I", data[end - 4 : end])[0]
        actual_crc = zlib.crc32(chunk_type + chunk_data) & 0xFFFFFFFF
        if expected_crc != actual_crc:
            raise ValueError(f"Invalid PNG CRC for {chunk_type!r}")
        parsed.append((chunk_type, chunk_data, data[start:end]))
        offset = end
        if chunk_type == b"IEND":
            saw_iend = True
            if offset != len(data):
                raise ValueError("Unexpected data after PNG IEND")
            break
    if not parsed or parsed[0][0] != b"IHDR" or len(parsed[0][1]) != 13:
        raise ValueError("PNG must start with a 13-byte IHDR")
    if not saw_iend:
        raise ValueError("PNG is missing IEND")
    return parsed


def _extract_itxt_keyword(data: bytes) -> str:
    separator = data.find(b"\x00")
    if separator <= 0:
        return ""
    return data[:separator].decode("latin-1", errors="replace")


def _decode_itxt(data: bytes) -> Tuple[str, str] | None:
    separator = data.find(b"\x00")
    if separator <= 0 or separator + 3 > len(data):
        return None
    keyword = data[:separator].decode("latin-1", errors="replace")
    compression_flag = data[separator + 1]
    compression_method = data[separator + 2]
    cursor = separator + 3
    language_end = data.find(b"\x00", cursor)
    if language_end < 0:
        return None
    translated_end = data.find(b"\x00", language_end + 1)
    if translated_end < 0:
        return None
    text_bytes = data[translated_end + 1 :]
    if compression_flag != 0 or compression_method != 0:
        return None
    if len(text_bytes) > _MAX_TEXT_BYTES:
        return None
    return keyword, text_bytes.decode("utf-8", errors="replace")


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


__all__ = [
    "inject_png_itxt_chunks",
    "read_png_itxt_chunks",
]
