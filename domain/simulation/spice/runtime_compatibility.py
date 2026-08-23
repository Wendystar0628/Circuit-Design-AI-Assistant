from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Tuple


# These constructs occur in Analog Devices' LTspice macro-models and are not
# accepted by the ngspice runtime shipped with this application.  Detection is
# advisory: source cards are never removed or replaced with a different model.
_UNSUPPORTED_LIBRARY_PATTERNS: Tuple[Tuple[str, re.Pattern[str]], ...] = (
    ("OTA", re.compile(r"^\s*A\S*\s+.*\bOTA\b", re.IGNORECASE | re.MULTILINE)),
    ("noiseless", re.compile(r"\bnoiseless\b", re.IGNORECASE)),
    ("uplim", re.compile(r"\buplim\s*\(", re.IGNORECASE)),
    ("dnlim", re.compile(r"\bdnlim\s*\(", re.IGNORECASE)),
)
_MODEL_PATTERN = re.compile(r"^\s*\.model\s+([^\s]+)", re.IGNORECASE | re.MULTILINE)
_SUBCKT_PATTERN = re.compile(r"^\s*\.subckt\s+([^\s(]+)", re.IGNORECASE | re.MULTILINE)


@dataclass(frozen=True)
class SpiceLibraryCompatibility:
    file_path: str
    is_compatible: bool
    model_names: Tuple[str, ...]
    subckt_names: Tuple[str, ...]
    incompatible_reasons: Tuple[str, ...]


def analyze_spice_library_file(file_path: Path) -> SpiceLibraryCompatibility:
    resolved_path = Path(file_path).expanduser().resolve()
    if not resolved_path.is_file():
        return SpiceLibraryCompatibility(
            file_path=str(resolved_path),
            is_compatible=False,
            model_names=(),
            subckt_names=(),
            incompatible_reasons=("文件不存在",),
        )

    content = _read_optional_text(resolved_path)
    if not content:
        return SpiceLibraryCompatibility(
            file_path=str(resolved_path),
            is_compatible=False,
            model_names=(),
            subckt_names=(),
            incompatible_reasons=("文件不可读或为空",),
        )

    reasons = tuple(label for label, pattern in _UNSUPPORTED_LIBRARY_PATTERNS if pattern.search(content))
    models = tuple(sorted({match.group(1).strip().lower() for match in _MODEL_PATTERN.finditer(content)}))
    subckts = tuple(sorted({match.group(1).strip().lower() for match in _SUBCKT_PATTERN.finditer(content)}))
    return SpiceLibraryCompatibility(
        file_path=str(resolved_path),
        is_compatible=not reasons,
        model_names=models,
        subckt_names=subckts,
        incompatible_reasons=reasons,
    )


def _read_optional_text(file_path: Path) -> str:
    for encoding in ("utf-8", "latin1", "cp1252"):
        try:
            return file_path.read_text(encoding=encoding)
        except (OSError, UnicodeError):
            continue
    return ""


__all__ = [
    "SpiceLibraryCompatibility",
    "analyze_spice_library_file",
]
