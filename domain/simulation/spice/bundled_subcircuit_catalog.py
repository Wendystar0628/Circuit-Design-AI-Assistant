from __future__ import annotations

import functools
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Tuple

from resources.resource_loader import get_spice_sub_dir


@dataclass(frozen=True)
class BundledSubcircuitHeader:
    name: str
    source_file: Path
    ports: Tuple[str, ...]
    leading_comment_lines: Tuple[str, ...]
    trailing_lines: Tuple[str, ...]


_CATALOG_FILE_PATTERNS: Tuple[str, ...] = ("*.lib", "*.sub", "*.cir", "*.sp", "*.ckt", "*.mod")
_SUBCKT_HEADER_PATTERN = re.compile(r"^\s*\.subckt\s+([^\s(]+)(.*)$", re.IGNORECASE)


@functools.lru_cache(maxsize=1)
def load_bundled_subcircuit_catalog() -> Tuple[BundledSubcircuitHeader, ...]:
    sub_dir = get_spice_sub_dir()
    if not sub_dir.exists():
        return ()

    headers = []
    seen_files = set()
    for pattern in _CATALOG_FILE_PATTERNS:
        for file_path in sorted(sub_dir.rglob(pattern)):
            normalized_file_path = str(file_path.resolve()).lower()
            if normalized_file_path in seen_files:
                continue
            seen_files.add(normalized_file_path)
            lines = _read_bundled_text_lines(file_path)
            if not lines:
                continue
            for index, line in enumerate(lines):
                match = _SUBCKT_HEADER_PATTERN.match(line)
                if match is None:
                    continue
                ports = tuple(token for token in match.group(2).split() if token)
                headers.append(
                    BundledSubcircuitHeader(
                        name=match.group(1).strip().lower(),
                        source_file=file_path,
                        ports=ports,
                        leading_comment_lines=tuple(lines[max(0, index - 16):index]),
                        trailing_lines=tuple(lines[index + 1:min(len(lines), index + 32)]),
                    )
                )
    return tuple(headers)


@functools.lru_cache(maxsize=1)
def load_bundled_subcircuit_path_index() -> Dict[str, Path]:
    index: Dict[str, Path] = {}
    for header in load_bundled_subcircuit_catalog():
        index.setdefault(header.name, header.source_file)
    return index


def iter_bundled_subcircuit_names() -> Iterable[str]:
    for header in load_bundled_subcircuit_catalog():
        yield header.name


def _read_bundled_text_lines(file_path: Path) -> Tuple[str, ...]:
    for encoding in ("utf-8", "latin1"):
        try:
            return tuple(file_path.read_text(encoding=encoding, errors="ignore").splitlines())
        except Exception:
            continue
    return ()


__all__ = [
    "BundledSubcircuitHeader",
    "iter_bundled_subcircuit_names",
    "load_bundled_subcircuit_catalog",
    "load_bundled_subcircuit_path_index",
]
