"""Numerical sensitivity checks on a frozen experiment, not physical validation.

ngspice defaults used here are RELTOL=1e-3, ABSTOL=1e-12 A,
VNTOL=1e-6 V, and TRAN tmax=min(tstep, (tstop-tstart)/50).
Sources: https://ngspice.sourceforge.io/docs/ngspice-manual.pdf,
sections ``DC Solution Options`` and ``.TRAN: Transient Analysis``.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, replace
from numbers import Real
from typing import Any, Mapping

from domain.simulation.models.acceptance import convert_metric_value, resolve_native_measurement
from domain.simulation.models.experiment import ExperimentSpec
from domain.simulation.models.simulation_result import SimulationResult
from domain.simulation.spice.directive_tokenizer import tokenize_spice_directive
from domain.simulation.spice.experiment_deck import compile_experiment_graph, source_solver_options
from domain.simulation.spice.numeric import parse_spice_number
from domain.simulation.spice.source_closure import SpiceSourceClosureGraph, restore_spice_source_graph


DEFAULT_TOLERANCES = {"reltol": 1e-3, "abstol": 1e-12, "vntol": 1e-6}
_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _finite(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(float(value)):
        raise ValueError(f"{field} must be a finite JSON number")
    return float(value)


@dataclass(frozen=True)
class NumericalMetricSpec:
    name: str
    unit: str
    absolute_tolerance: float = 0.0
    relative_tolerance: float = 0.01

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or _NAME.fullmatch(self.name) is None:
            raise ValueError("numerical metric name must be a SPICE measurement identifier")
        if (not isinstance(self.unit, str) or not self.unit.strip() or len(self.unit) > 32
                or any(c in self.unit for c in "\r\n\x00")):
            raise ValueError("numerical metric unit must be a nonempty unit string")
        object.__setattr__(self, "name", self.name.casefold())
        object.__setattr__(self, "unit", self.unit.strip())
        for field in ("absolute_tolerance", "relative_tolerance"):
            value = _finite(getattr(self, field), field)
            if value < 0:
                raise ValueError(f"{field} must be nonnegative")
            object.__setattr__(self, field, value)

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "unit": self.unit,
                "absolute_tolerance": self.absolute_tolerance,
                "relative_tolerance": self.relative_tolerance}

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "NumericalMetricSpec":
        if not isinstance(payload, Mapping) or set(payload) - {
            "name", "unit", "absolute_tolerance", "relative_tolerance",
        } or not {"name", "unit"} <= set(payload):
            raise ValueError("numerical metric requires name, unit, and optional absolute/relative tolerances")
        return cls(**dict(payload))


@dataclass(frozen=True)
class NumericalStudySpec:
    metrics: tuple[NumericalMetricSpec, ...]
    tolerance_factor: float = 0.1
    max_timestep_factor: float = 0.5

    def __post_init__(self) -> None:
        if not isinstance(self.metrics, (tuple, list)) or not self.metrics or len(self.metrics) > 100:
            raise ValueError("numerical metrics must contain between 1 and 100 measurements")
        metrics = tuple(item if isinstance(item, NumericalMetricSpec) else NumericalMetricSpec.from_dict(item)
                        for item in self.metrics)
        if len({item.name for item in metrics}) != len(metrics):
            raise ValueError("numerical metrics must have unique names")
        object.__setattr__(self, "metrics", metrics)
        for field in ("tolerance_factor", "max_timestep_factor"):
            value = _finite(getattr(self, field), field)
            if not 0 < value < 1:
                raise ValueError(f"{field} must be strictly between zero and one")
            object.__setattr__(self, field, value)

    def to_dict(self) -> dict[str, Any]:
        return {"metrics": [item.to_dict() for item in self.metrics],
                "tolerance_factor": self.tolerance_factor,
                "max_timestep_factor": self.max_timestep_factor}

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "NumericalStudySpec":
        if not isinstance(payload, Mapping) or set(payload) - {
            "metrics", "tolerance_factor", "max_timestep_factor",
        } or "metrics" not in payload:
            raise ValueError("numerical study requires metrics and optional refinement factors")
        return cls(**dict(payload))


def _tran_settings(command: str) -> tuple[list[str], float, bool]:
    tokens = list(tokenize_spice_directive(command))
    uic = tokens[-1].casefold() == "uic"
    numeric = tokens[:-1] if uic else tokens
    step, stop = parse_spice_number(numeric[1]), parse_spice_number(numeric[2])
    start = parse_spice_number(numeric[3]) if len(numeric) > 3 else 0.0
    tmax = parse_spice_number(numeric[4]) if len(numeric) > 4 else min(step, (stop - start) / 50.0)
    return numeric[:3] + ([numeric[3]] if len(numeric) > 3 else ["0"]), tmax, uic


def _tran_command(command: str, factor: float = 1.0) -> str:
    head, tmax, uic = _tran_settings(command)
    tightened = tmax * factor
    if not math.isfinite(tightened) or tightened <= 0 or (factor < 1 and tightened >= tmax):
        raise ValueError("Requested maximum timestep cannot be represented as a positive stricter value")
    return " ".join([*head, f"{tightened:.17g}", *(["uic"] if uic else [])])


def build_numerical_experiments(
    base: ExperimentSpec, source_graph: SpiceSourceClosureGraph, spec: NumericalStudySpec,
) -> tuple[ExperimentSpec, ExperimentSpec]:
    """Build a baseline/refined pair from the same captured source graph.

    Freeze effective source controls and documented tolerance defaults into the
    baseline. Refine tolerances and, for TRAN only, the actual integration tmax;
    leave tstep (which can affect stimulus defaults), tstop, tstart, UIC,
    integration method, parameters, temperature, and model bytes unchanged.
    The caller must execute both specs with this same source snapshot.
    """
    effective, command, _ = compile_experiment_graph(source_graph, base)
    options = {key: f"{value:.17g}" for key, value in DEFAULT_TOLERANCES.items()}
    options.update(source_solver_options(effective.active_views))
    baseline_command = _tran_command(command) if command.split()[0].casefold() == ".tran" else command
    baseline = replace(base, analysis_command=baseline_command, solver_options=options)
    refined_options = dict(options)
    for key in DEFAULT_TOLERANCES:
        value = parse_spice_number(options[key])
        tightened = value * spec.tolerance_factor
        if not math.isfinite(tightened) or not 0 < tightened < value:
            raise ValueError(f"Requested {key} refinement is not a representable stricter tolerance")
        refined_options[key] = f"{tightened:.17g}"
    refined_command = (
        _tran_command(baseline_command, spec.max_timestep_factor)
        if baseline_command.split()[0].casefold() == ".tran" else baseline_command
    )
    # ExperimentSpec also rejects underflow below the supported native ranges.
    refined = replace(baseline, analysis_command=refined_command, solver_options=refined_options)
    return baseline, refined


def _analysis_conditions(command: str) -> tuple[Any, ...]:
    tokens = tokenize_spice_directive(command)
    if tokens[0].casefold() == ".tran":
        head, _, uic = _tran_settings(command)
        return (".tran", *(parse_spice_number(item) for item in head[1:]), uic)
    return tuple(token.casefold() for token in tokens)


def _provenance_reason(baseline: SimulationResult, refined: SimulationResult) -> str:
    """Check persisted proof when present; caller attests snapshot identity otherwise."""
    left, right = baseline.provenance, refined.provenance
    if not left and not right:
        return ""
    if not left or not right:
        return "Both runs require matching input provenance"
    try:
        original_left = restore_spice_source_graph(left["original_source"])
        original_right = restore_spice_source_graph(right["original_source"])
        if original_left.digest != original_right.digest:
            return "Source or model snapshots differ between runs"
        if left.get("engine") != right.get("engine"):
            return "Simulation engines differ between runs"
        specs = [ExperimentSpec.from_dict(item["experiment"]) for item in (left, right)]
        for result, item, original, experiment in zip(
            (baseline, refined), (left, right), (original_left, original_right), specs,
        ):
            effective, command, _ = compile_experiment_graph(original, experiment)
            if (effective.digest != result.source_digest
                    or restore_spice_source_graph(item["effective_source"]).digest != effective.digest
                    or command != result.analysis_command):
                return "Result input identity does not match its captured experiment"
        first, second = specs
        if first.parameters != second.parameters or first.temperature != second.temperature:
            return "Operating conditions differ between runs"
        def other(values):
            return {key: value for key, value in values.items() if key not in DEFAULT_TOLERANCES}
        if other(first.solver_options) != other(second.solver_options):
            return "Solver controls other than tolerances differ between runs"
        for key in DEFAULT_TOLERANCES:
            before = parse_spice_number(first.solver_options.get(key, ""))
            after = parse_spice_number(second.solver_options.get(key, ""))
            if before is None or after is None or not 0 < after < before:
                return "Refined solver tolerances are not strictly tighter"
        if baseline.analysis_type == "tran":
            if _tran_settings(refined.analysis_command)[1] >= _tran_settings(baseline.analysis_command)[1]:
                return "Refined maximum timestep is not strictly tighter"
    except (ValueError, TypeError, KeyError, IndexError):
        return "Input provenance cannot establish comparable experiments"
    return ""


def compare_numerical_results(
    baseline: SimulationResult, refined: SimulationResult, spec: NumericalStudySpec,
    *, comparable: bool = False,
) -> dict[str, Any]:
    """Compare selected native measures with explicit frozen-input attestation.

    ``comparable=True`` means the orchestration verified that both cases derive
    from the same frozen source/model snapshot and base operating conditions.
    Available run provenance is checked as well. A stable outcome is restricted
    to this pair and these metrics; it does not establish physical model accuracy.
    """
    reason = "" if comparable is True else "Frozen input and operating-condition identity was not verified"
    if not baseline.success or not refined.success:
        reason = "Both simulations must complete successfully"
    elif baseline.analysis_type != refined.analysis_type or (
        _analysis_conditions(baseline.analysis_command) != _analysis_conditions(refined.analysis_command)
    ):
        reason = "Analysis or operating conditions differ between runs"
    elif not reason:
        reason = _provenance_reason(baseline, refined)
    rows = []
    for target in spec.metrics:
        row = {"name": target.name, "unit": target.unit,
               "baseline_value": None, "refined_value": None,
               "absolute_delta": None, "relative_delta": None, "allowed_delta": None,
               "stable": False, "status": "inconclusive", "reason": reason,
               "absolute_tolerance": target.absolute_tolerance,
               "relative_tolerance": target.relative_tolerance}
        matches = [[item for item in result.measurements or [] if item.name.casefold() == target.name]
                   for result in (baseline, refined)]
        if any(len(items) != 1 for items in matches):
            row["reason"] = reason or "Selected measurement is missing or ambiguous"
        else:
            first, second = matches[0][0], matches[1][0]
            if not first.is_valid or not second.is_valid:
                row["reason"] = reason or "Selected measurement was not measured successfully in both runs"
            elif " ".join(first.statement.split()).casefold() != " ".join(second.statement.split()).casefold():
                row["reason"] = reason or "Measurement definitions differ between runs"
            else:
                values = []
                metric_reason = ""
                for result in (baseline, refined):
                    value, unit, error = resolve_native_measurement(result, target.name)
                    if not error:
                        value, error = convert_metric_value(value, unit, target.unit)
                    if error:
                        metric_reason = error
                        break
                    values.append(value)
                if metric_reason:
                    row["reason"] = reason or metric_reason
                    rows.append(row)
                    continue
                before, after = values
                row.update(baseline_value=before, refined_value=after)
                delta = abs(after - before)
                allowed = target.absolute_tolerance + target.relative_tolerance * abs(before)
                relative = delta / abs(before) if before else None
                if not math.isfinite(delta) or not math.isfinite(allowed):
                    row["reason"] = reason or "Metric difference or tolerance exceeds finite numeric range"
                else:
                    row.update(absolute_delta=delta, allowed_delta=allowed,
                               relative_delta=relative if relative is None or math.isfinite(relative) else None)
                    if not reason:
                        stable = delta <= allowed
                        row.update(stable=stable, status="stable" if stable else "unstable",
                                   reason="" if stable else "Metric change exceeds the selected tolerance")
        rows.append(row)
    status = ("inconclusive" if any(row["status"] == "inconclusive" for row in rows)
              else "stable" if all(row["stable"] for row in rows) else "unstable")
    duration = [result.duration_seconds for result in (baseline, refined)]
    ratio = duration[1] / duration[0] if duration[0] else None
    total = sum(duration)
    return {"status": status, "stable": status == "stable",
            "reason": reason or next((row["reason"] for row in rows if row["reason"]), ""),
            "metrics": rows,
            "cost": {"baseline_seconds": duration[0], "refined_seconds": duration[1],
                     "total_seconds": total if math.isfinite(total) else None,
                     "ratio": ratio if ratio is None or math.isfinite(ratio) else None}}


__all__ = ["NumericalMetricSpec", "NumericalStudySpec", "DEFAULT_TOLERANCES",
           "build_numerical_experiments", "compare_numerical_results"]
