"""Canonical structured errors produced by simulation executors."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Mapping, Optional


_SERIALIZED_FIELDS = (
    "code",
    "type",
    "severity",
    "message",
    "file_path",
    "line_number",
    "context",
    "details",
    "recovery_attempted",
    "recovery_result",
    "recovery_suggestion",
    "raw_output",
)
_SERIALIZED_FIELD_SET = frozenset(_SERIALIZED_FIELDS)


class SimulationErrorType(Enum):
    """Stable error categories; the enum value is the canonical code."""

    SYNTAX_ERROR = "E001"
    MODEL_MISSING = "E002"
    NODE_FLOATING = "E003"
    CONVERGENCE_DC = "E004"
    CONVERGENCE_TRAN = "E005"
    TIMEOUT = "E006"
    MEMORY_OVERFLOW = "E007"
    NGSPICE_CRASH = "E008"
    FILE_ACCESS = "E009"
    PARAMETER_INVALID = "E010"
    SCRIPT_ERROR = "E011"
    OUTPUT_PARSE_ERROR = "E012"
    DEPENDENCY_MISSING = "E013"
    CANCELLED = "E014"


class ErrorSeverity(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class SimulationError:
    """Serializable simulation failure with one authoritative type/code.

    ``code`` is deliberately not a writable constructor field.  The former
    two-source design allowed impossible pairs such as ``code='E011'`` with
    ``type=PARAMETER_INVALID`` (``E010``), which then leaked contradictory
    diagnostics into persisted bundles.
    """

    type: SimulationErrorType
    severity: ErrorSeverity
    message: str
    file_path: Optional[str] = None
    line_number: Optional[int] = None
    context: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)
    recovery_attempted: bool = False
    recovery_result: Optional[str] = None
    recovery_suggestion: Optional[str] = None
    raw_output: Optional[str] = None

    def __post_init__(self) -> None:
        if not isinstance(self.type, SimulationErrorType):
            raise TypeError("type must be SimulationErrorType")
        if not isinstance(self.severity, ErrorSeverity):
            raise TypeError("severity must be ErrorSeverity")
        if not isinstance(self.message, str) or not self.message.strip():
            raise ValueError("message must be a non-empty string")
        self.message = self.message.strip()
        if self.line_number is not None and (
            isinstance(self.line_number, bool)
            or not isinstance(self.line_number, int)
            or self.line_number < 1
        ):
            raise ValueError("line_number must be a positive integer")
        for field_name in (
            "file_path",
            "context",
            "recovery_result",
            "recovery_suggestion",
            "raw_output",
        ):
            value = getattr(self, field_name)
            if value is not None and not isinstance(value, str):
                raise TypeError(f"{field_name} must be a string or None")
        if type(self.recovery_attempted) is not bool:
            raise TypeError("recovery_attempted must be a boolean")
        if not isinstance(self.details, dict):
            raise TypeError("details must be a dictionary")
        self.details = dict(self.details)

    @property
    def code(self) -> str:
        """Canonical error code derived from :attr:`type`."""

        return self.type.value

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "type": self.type.value,
            "severity": self.severity.value,
            "message": self.message,
            "file_path": self.file_path,
            "line_number": self.line_number,
            "context": self.context,
            "details": dict(self.details),
            "recovery_attempted": self.recovery_attempted,
            "recovery_result": self.recovery_result,
            "recovery_suggestion": self.recovery_suggestion,
            "raw_output": self.raw_output,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SimulationError":
        if not isinstance(data, Mapping):
            raise TypeError("simulation error payload must be a mapping")
        missing = tuple(field for field in _SERIALIZED_FIELDS if field not in data)
        unknown = tuple(field for field in data if field not in _SERIALIZED_FIELD_SET)
        if missing or unknown:
            details = []
            if missing:
                details.append(f"missing={list(missing)!r}")
            if unknown:
                details.append(f"unknown={list(unknown)!r}")
            raise ValueError(
                "simulation error payload must contain the exact canonical keys"
                + (f" ({', '.join(details)})" if details else "")
            )

        error_type = SimulationErrorType(data["type"])
        serialized_code = data["code"]
        if serialized_code != error_type.value:
            raise ValueError(
                "simulation error code contradicts its type: "
                f"{serialized_code!r} != {error_type.value!r}"
            )
        details = data["details"]
        if not isinstance(details, dict):
            raise TypeError("simulation error details must be an object")
        recovery_attempted = data["recovery_attempted"]
        if type(recovery_attempted) is not bool:
            raise TypeError(
                "simulation error recovery_attempted must be a boolean"
            )
        optional_strings = {
            field_name: data[field_name]
            for field_name in (
                "file_path",
                "context",
                "recovery_result",
                "recovery_suggestion",
                "raw_output",
            )
        }
        for field_name, value in optional_strings.items():
            if value is not None and not isinstance(value, str):
                raise TypeError(
                    f"simulation error {field_name} must be a string or null"
                )
        return cls(
            type=error_type,
            severity=ErrorSeverity(data["severity"]),
            message=data["message"],
            file_path=optional_strings["file_path"],
            line_number=data["line_number"],
            context=optional_strings["context"],
            details=dict(details),
            recovery_attempted=recovery_attempted,
            recovery_result=optional_strings["recovery_result"],
            recovery_suggestion=optional_strings["recovery_suggestion"],
            raw_output=optional_strings["raw_output"],
        )


__all__ = ["ErrorSeverity", "SimulationError", "SimulationErrorType"]
