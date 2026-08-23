"""Canonical result type for ngspice ``.measure`` output."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from numbers import Real
from typing import Any, Dict, Optional


class MeasureStatus(Enum):
    OK = "OK"
    FAILED = "FAILED"
    PARSE_ERROR = "PARSE_ERROR"


@dataclass
class MeasureResult:
    name: str
    value: Optional[float] = None
    status: MeasureStatus = MeasureStatus.OK
    statement: str = ""
    raw_output: str = ""
    error_message: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "value": float(self.value) if self.is_valid else None,
            "status": self.status.value,
            "statement": self.statement,
            "raw_output": self.raw_output,
            "error_message": self.error_message,
        }

    @property
    def is_valid(self) -> bool:
        return self.status is MeasureStatus.OK and _finite_number(self.value) is not None


def _finite_number(value: object) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, Real):
        return None
    converted = float(value)
    return converted if math.isfinite(converted) else None
