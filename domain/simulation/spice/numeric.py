"""ngspice numeric literal parsing shared by directives and source editing."""

from __future__ import annotations

import math
import re
from typing import Optional


_NUMERIC_PATTERN = re.compile(
    r"^([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)([A-Za-z]+)?$"
)
_SUFFIX_SCALES = {
    "t": 1e12,
    "g": 1e9,
    "meg": 1e6,
    "k": 1e3,
    "mil": 25.4e-6,
    "m": 1e-3,
    "u": 1e-6,
    "n": 1e-9,
    "p": 1e-12,
    "f": 1e-15,
    "a": 1e-18,
}
_FORMAT_SCALES = (
    (1e12, "T"),
    (1e9, "G"),
    (1e6, "Meg"),
    (1e3, "k"),
    (1.0, ""),
    (1e-3, "m"),
    (1e-6, "u"),
    (1e-9, "n"),
    (1e-12, "p"),
    (1e-15, "f"),
    (1e-18, "a"),
)


def parse_spice_number(token: str) -> Optional[float]:
    """Parse one ngspice number, including its case-insensitive scale suffix.

    ngspice treats letters after a number as an optional scale factor followed
    by ignored unit text.  Therefore ``10ms`` is 10 milli-units, ``1MegHz`` is
    one million, and ``10V`` is ten.  ``M`` is milli; mega must be written
    ``Meg``.
    """

    match = _NUMERIC_PATTERN.fullmatch(str(token or "").strip())
    if match is None:
        return None
    try:
        base_value = float(match.group(1))
    except ValueError:
        return None
    if not math.isfinite(base_value):
        return None

    suffix = str(match.group(2) or "").lower()
    if not suffix:
        return base_value
    if suffix.startswith("meg"):
        scale = _SUFFIX_SCALES["meg"]
    elif suffix.startswith("mil"):
        scale = _SUFFIX_SCALES["mil"]
    else:
        # A leading recognized scale letter is significant; all following
        # letters are unit text.  If the first letter is not a scale factor,
        # ngspice ignores the entire suffix (for example ``10Volts``).
        scale = _SUFFIX_SCALES.get(suffix[0], 1.0)
    value = base_value * scale
    return value if math.isfinite(value) else None


def is_spice_number(token: str) -> bool:
    return parse_spice_number(token) is not None


def format_spice_number(value: float) -> str:
    numeric_value = float(value)
    if not math.isfinite(numeric_value):
        raise ValueError("SPICE number must be finite")
    absolute = abs(numeric_value)
    if absolute == 0:
        return "0"
    for scale, suffix in _FORMAT_SCALES:
        scaled = numeric_value / scale
        if 1 <= abs(scaled) < 1000:
            return f"{scaled:.12g}{suffix}"
    return f"{numeric_value:.12g}"


__all__ = ["format_spice_number", "is_spice_number", "parse_spice_number"]
