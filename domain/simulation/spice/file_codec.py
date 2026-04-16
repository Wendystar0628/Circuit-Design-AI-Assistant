from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SpiceSourceFile:
    file_path: str
    source_text: str
    encoding: str
    newline: str


def read_spice_source_file(file_path: str) -> SpiceSourceFile:
    path = Path(file_path)
    raw_bytes = path.read_bytes()
    encoding = _detect_encoding(raw_bytes)
    source_text = raw_bytes.decode(encoding)
    return SpiceSourceFile(
        file_path=str(path),
        source_text=source_text,
        encoding=encoding,
        newline=_detect_newline(raw_bytes),
    )


def write_spice_source_file(snapshot: SpiceSourceFile, source_text: str) -> None:
    path = Path(snapshot.file_path)
    path.write_bytes(str(source_text).encode(snapshot.encoding))


def _detect_encoding(raw_bytes: bytes) -> str:
    if raw_bytes.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    for encoding in ("utf-8", "gb18030", "latin-1"):
        try:
            raw_bytes.decode(encoding)
            return encoding
        except UnicodeDecodeError:
            continue
    return "latin-1"


def _detect_newline(raw_bytes: bytes) -> str:
    if b"\r\n" in raw_bytes:
        return "\r\n"
    if b"\r" in raw_bytes:
        return "\r"
    return "\n"


__all__ = ["SpiceSourceFile", "read_spice_source_file", "write_spice_source_file"]
