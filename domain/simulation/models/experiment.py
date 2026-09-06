"""Explicit, serializable controls for one reproducible SPICE experiment."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Mapping

from domain.simulation.spice.analysis_directive import validate_analysis_command
from domain.simulation.spice.directive_tokenizer import tokenize_spice_directive
from domain.simulation.spice.numeric import parse_spice_number


_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_FIELDS = frozenset({
    "analysis_command", "parameters", "temperature", "solver_options", "timeout_seconds",
    "acceptance_constraints", "model_bindings",
})
# Product-supported solver controls. Ranges reject native clamping and zero tolerances.
SOLVER_OPTION_RANGES = {
    "reltol": (1e-15, 0.1), "abstol": (1e-30, 1.0),
    "vntol": (1e-30, 1.0), "gmin": (0.0, 1.0),
    "itl1": (1, 1000000), "itl4": (1, 1000000), "maxord": (1, 6),
}
_INTEGER_OPTIONS = frozenset({"itl1", "itl4", "maxord"})


def validate_solver_options(options: Mapping[str, Any]) -> dict[str, str]:
    if not isinstance(options, Mapping):
        raise ValueError("solver_options must be an object")
    normalized: dict[str, str] = {}
    for name, value in options.items():
        if not isinstance(name, str):
            raise ValueError("solver option names must be strings")
        key = name.casefold()
        if key in normalized:
            raise ValueError(f"Duplicate solver option: {name}")
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            raise ValueError(f"Invalid solver option value: {name}")
        literal = str(value).strip()
        if key == "method":
            literal = literal.casefold()
            if literal not in {"trap", "gear"}:
                raise ValueError("method must be trap or gear")
        elif key in SOLVER_OPTION_RANGES:
            numeric = parse_spice_number(literal)
            lower, upper = SOLVER_OPTION_RANGES[key]
            if numeric is None or not lower <= numeric <= upper:
                raise ValueError(f"{key} must be a finite number in [{lower:g}, {upper:g}]")
            if key in _INTEGER_OPTIONS and not numeric.is_integer():
                raise ValueError(f"{key} must be an integer")
            literal = str(int(numeric)) if key in _INTEGER_OPTIONS else f"{numeric:.17g}"
        else:
            raise ValueError(f"Unsupported solver option: {name}")
        normalized[key] = literal
    if normalized.get("method", "trap") == "trap" and int(normalized.get("maxord", "2")) > 2:
        raise ValueError("trap integration supports maxord 1 or 2; choose gear for higher orders")
    return normalized


@dataclass(frozen=True)
class ExperimentSpec:
    """One analysis and literal overrides; empty analysis uses the unique source card.

    Parameter overrides bind existing top-level .param declarations in the main
    deck. Unknown and subcircuit-local parameters are errors. Celsius temperature
    replaces source .temp cards; solver controls replace controls with the same name.
    """

    analysis_command: str = ""
    parameters: dict[str, str] = field(default_factory=dict)
    temperature: float | None = None
    solver_options: dict[str, str] = field(default_factory=dict)
    timeout_seconds: float = 300.0
    acceptance_constraints: list[dict[str, Any]] = field(default_factory=list)
    model_bindings: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not isinstance(self.analysis_command, str):
            raise ValueError("analysis_command must be a string")
        command = self.analysis_command.strip()
        if command:
            tokens = tokenize_spice_directive(command)
            analysis = tokens[0].casefold().removeprefix(".") if tokens else ""
            if analysis not in {"ac", "dc", "tran", "noise", "op"}:
                raise ValueError("analysis_command must select AC, DC, TRAN, NOISE, or OP")
            validate_analysis_command(analysis_type=analysis, analysis_command=command)
        object.__setattr__(self, "analysis_command", command)
        if not isinstance(self.parameters, Mapping):
            raise ValueError("parameters must be an object")
        parameters: dict[str, str] = {}
        for name, value in self.parameters.items():
            if not isinstance(name, str) or _NAME.fullmatch(name) is None:
                raise ValueError(f"Invalid parameter name: {name!r}")
            key = name.casefold()
            if key in parameters:
                raise ValueError(f"Duplicate parameter: {name}")
            if isinstance(value, bool) or not isinstance(value, (str, int, float)):
                raise ValueError(f"Parameter {name} requires a finite SPICE numeric literal")
            literal = str(value).strip()
            if parse_spice_number(literal) is None:
                raise ValueError(f"Parameter {name} requires a finite SPICE numeric literal")
            parameters[key] = literal
        object.__setattr__(self, "parameters", parameters)
        if self.temperature is not None:
            if isinstance(self.temperature, bool):
                raise ValueError("temperature must be finite Celsius above absolute zero")
            try:
                temperature = float(self.temperature)
            except (TypeError, ValueError) as exc:
                raise ValueError("temperature must be finite Celsius above absolute zero") from exc
            if not math.isfinite(temperature) or temperature <= -273.15:
                raise ValueError("temperature must be finite Celsius above absolute zero")
            object.__setattr__(self, "temperature", temperature)
        object.__setattr__(self, "solver_options", validate_solver_options(self.solver_options))
        if isinstance(self.timeout_seconds, bool):
            raise ValueError("timeout_seconds must be a positive finite number")
        try:
            timeout = float(self.timeout_seconds)
        except (TypeError, ValueError) as exc:
            raise ValueError("timeout_seconds must be a positive finite number") from exc
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout_seconds must be a positive finite number")
        object.__setattr__(self, "timeout_seconds", timeout)
        from domain.simulation.models.acceptance import validate_acceptance_constraints
        from domain.simulation.models.model_manifest import validate_model_bindings

        object.__setattr__(self, "acceptance_constraints", validate_acceptance_constraints(self.acceptance_constraints))
        object.__setattr__(self, "model_bindings", validate_model_bindings(self.model_bindings))

    def to_dict(self) -> dict[str, Any]:
        import copy

        return {
            "analysis_command": self.analysis_command,
            "parameters": dict(self.parameters), "temperature": self.temperature,
            "solver_options": dict(self.solver_options), "timeout_seconds": self.timeout_seconds,
            "acceptance_constraints": copy.deepcopy(self.acceptance_constraints),
            "model_bindings": copy.deepcopy(self.model_bindings),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ExperimentSpec":
        if not isinstance(payload, Mapping):
            raise ValueError("experiment must be an object")
        unknown = set(payload) - _FIELDS
        if unknown:
            raise ValueError(f"Unknown experiment fields: {sorted(unknown)}")
        return cls(**dict(payload))


__all__ = ["ExperimentSpec", "SOLVER_OPTION_RANGES", "validate_solver_options"]
