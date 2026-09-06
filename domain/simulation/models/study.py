"""Explicit corner axes and deterministic Cartesian experiment inputs."""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from domain.simulation.models.experiment import ExperimentSpec
from domain.simulation.spice.numeric import parse_spice_number


MAX_STUDY_CASES = 64


@dataclass(frozen=True)
class CornerAxis:
    kind: str
    values: tuple[str | float, ...]
    parameter: str = ""

    def __post_init__(self) -> None:
        if self.kind not in {"parameter", "temperature", "supply", "load"}:
            raise ValueError("axis kind must be parameter, temperature, supply, or load")
        if not isinstance(self.values, (list, tuple)) or not self.values:
            raise ValueError("axis values must be a non-empty array")
        if len(self.values) > MAX_STUDY_CASES:
            raise ValueError(f"axis has more than {MAX_STUDY_CASES} values")
        normalized: list[str | float] = []
        numeric_values: set[float] = set()
        if self.kind == "temperature":
            if self.parameter:
                raise ValueError("temperature axis must not specify a parameter")
            for value in self.values:
                parsed = ExperimentSpec(temperature=value).temperature
                if parsed in numeric_values:
                    raise ValueError("axis contains duplicate numeric values")
                numeric_values.add(parsed)
                normalized.append(parsed)
        else:
            if not isinstance(self.parameter, str) or not self.parameter:
                raise ValueError("parameter, supply, and load axes require an explicit .param name")
            for value in self.values:
                spec = ExperimentSpec(parameters={self.parameter: value})
                literal = next(iter(spec.parameters.values()))
                numeric = parse_spice_number(literal)
                if numeric in numeric_values:
                    raise ValueError("axis contains duplicate numeric values")
                numeric_values.add(numeric)
                normalized.append(literal)
            object.__setattr__(self, "parameter", self.parameter.casefold())
        object.__setattr__(self, "values", tuple(normalized))

    @property
    def key(self) -> str:
        return "temperature" if self.kind == "temperature" else f"{self.kind}:{self.parameter}"

    def to_dict(self) -> dict[str, Any]:
        payload = {"kind": self.kind, "values": list(self.values)}
        if self.parameter:
            payload["parameter"] = self.parameter
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "CornerAxis":
        if not isinstance(payload, Mapping):
            raise ValueError("each axis must be an object")
        unknown = set(payload) - {"kind", "values", "parameter"}
        if unknown:
            raise ValueError(f"Unknown corner axis fields: {sorted(unknown)}")
        if "kind" not in payload or "values" not in payload:
            raise ValueError("each axis requires kind and values")
        return cls(**dict(payload))


def expand_corner_cases(
    base: ExperimentSpec, axes: Sequence[CornerAxis | Mapping[str, Any]],
) -> tuple[list[CornerAxis], list[dict[str, Any]]]:
    """Build independent specs; supply/load are named parameter bindings only."""
    if not isinstance(axes, (list, tuple)) or not axes:
        raise ValueError("corner study requires at least one axis")
    normalized = [axis if isinstance(axis, CornerAxis) else CornerAxis.from_dict(axis) for axis in axes]
    bindings: set[str] = set()
    count = 1
    for axis in normalized:
        binding = "temperature" if axis.kind == "temperature" else f"parameter:{axis.parameter}"
        if binding in bindings:
            raise ValueError(f"Multiple axes target the same control: {binding}")
        bindings.add(binding)
        count *= len(axis.values)
        if count > MAX_STUDY_CASES:
            raise ValueError(f"Corner matrix exceeds the {MAX_STUDY_CASES}-case limit")
    cases = []
    for index, values in enumerate(itertools.product(*(axis.values for axis in normalized)), 1):
        payload = base.to_dict()
        coordinates = {}
        for axis, value in zip(normalized, values):
            coordinates[axis.key] = value
            if axis.kind == "temperature":
                payload["temperature"] = value
            else:
                payload["parameters"][axis.parameter] = value
        experiment = ExperimentSpec.from_dict(payload)
        cases.append({
            "case_id": f"case_{index:03d}",
            "label": ", ".join(f"{key}={value}" for key, value in coordinates.items()),
            "coordinates": coordinates, "experiment": experiment.to_dict(),
        })
    return normalized, cases


__all__ = ["CornerAxis", "MAX_STUDY_CASES", "expand_corner_cases"]
