"""Frozen engineering limits evaluated against one native simulation result.

Bounds use the declared unit and are inclusive. Conditions match only explicit
experiment overrides: an unspecified source-deck temperature or parameter is
unknown, not an assumed nominal value. Native measurements whose dimensions
cannot be established from the statement never receive an acceptance PASS.
"""

from __future__ import annotations

import math
import re
from numbers import Real
from typing import Any, Mapping

from domain.simulation.measure.measure_metadata import measure_metadata_resolver
from domain.simulation.spice.directive_tokenizer import tokenize_spice_directive
from domain.simulation.spice.numeric import parse_spice_number


_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_FIELDS = {"id", "source", "metric", "unit", "lower", "upper", "conditions"}
_SIMPLE_VECTOR = re.compile(r"(?:V(?:DB|P|M|R|I)?|I|P)\([^()\s]+\)", re.IGNORECASE)
_PREFIXES = {"G": 1e9, "M": 1e6, "k": 1e3, "m": 1e-3, "u": 1e-6,
             "μ": 1e-6, "µ": 1e-6, "n": 1e-9, "p": 1e-12, "f": 1e-15}
_PREFIXABLE = {"V", "A", "W", "s", "Hz", "Ω", "S", "F", "H"}
_UNIT_ALIASES = {"ohm": "Ω", "Ohm": "Ω", "deg": "°", "degree": "°", "V/V": "1", "A/A": "1"}


def _finite(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, Real):
        return None
    try:
        number = float(value)
    except (OverflowError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or any(ord(ch) < 32 for ch in value):
        raise ValueError(f"{name} must be a non-empty single-line string")
    return value.strip()


def _conditions(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, Mapping) or set(payload) - {"parameters", "temperature"}:
        raise ValueError("acceptance conditions allow only parameters and temperature")
    output: dict[str, Any] = {}
    if "parameters" in payload:
        parameters = payload["parameters"]
        if not isinstance(parameters, Mapping):
            raise ValueError("acceptance condition parameters must be an object")
        normalized: dict[str, str] = {}
        for name, value in parameters.items():
            if not isinstance(name, str) or not _NAME.fullmatch(name):
                raise ValueError("acceptance condition parameter names must be SPICE identifiers")
            if name.casefold() in normalized:
                raise ValueError(f"Duplicate acceptance condition parameter: {name}")
            if isinstance(value, bool) or not isinstance(value, (str, int, float)):
                raise ValueError(f"Invalid acceptance condition parameter: {name}")
            literal = str(value).strip()
            if parse_spice_number(literal) is None:
                raise ValueError(f"Acceptance condition parameter {name} must be a finite SPICE literal")
            normalized[name.casefold()] = literal
        output["parameters"] = normalized
    if "temperature" in payload:
        temperature = _finite(payload["temperature"])
        if temperature is None or temperature <= -273.15:
            raise ValueError("acceptance condition temperature must be finite Celsius above absolute zero")
        output["temperature"] = temperature
    return output


def validate_acceptance_constraints(payload: Any) -> list[dict[str, Any]]:
    """Validate and copy a JSON list; callers archive this with the experiment.

    Each entry has ``metric``, ``unit``, and at least one of ``lower``/``upper``.
    Optional ``source`` is ``measurement`` (default) or ``op_signal``; ``id``
    defaults to the metric and must be unique. ``conditions`` may constrain
    parameter overrides and Celsius temperature. Unknown fields are errors.
    """
    if not isinstance(payload, list):
        raise ValueError("acceptance_constraints must be a list")
    if len(payload) > 128:
        raise ValueError("acceptance_constraints allows at most 128 constraints")
    normalized = []
    identities: set[str] = set()
    for item in payload:
        if not isinstance(item, Mapping) or set(item) - _FIELDS:
            raise ValueError("Each acceptance constraint must be an object containing only supported fields")
        metric = _text(item.get("metric"), "acceptance metric")
        source = item.get("source", "measurement")
        if source not in ("measurement", "op_signal"):
            raise ValueError("acceptance source must be measurement or op_signal")
        identity = _text(item.get("id", metric), "acceptance id")
        if identity.casefold() in identities:
            raise ValueError(f"Duplicate acceptance constraint id: {identity}")
        identities.add(identity.casefold())
        unit = _text(item.get("unit"), "acceptance unit")
        bounds: dict[str, float | None] = {}
        for name in ("lower", "upper"):
            value = item.get(name)
            bounds[name] = None if value is None else _finite(value)
            if value is not None and bounds[name] is None:
                raise ValueError(f"acceptance {name} must be a finite number or null")
        if bounds["lower"] is None and bounds["upper"] is None:
            raise ValueError("acceptance requires at least one lower or upper bound")
        if bounds["lower"] is not None and bounds["upper"] is not None and bounds["lower"] > bounds["upper"]:
            raise ValueError("acceptance lower must not exceed upper")
        normalized.append({"id": identity, "source": source, "metric": metric, "unit": unit,
                           **bounds, "conditions": _conditions(item.get("conditions", {}))})
    return normalized


def _get(value: Any, name: str, default: Any = None) -> Any:
    return value.get(name, default) if isinstance(value, Mapping) else getattr(value, name, default)


def _condition_reason(conditions: Mapping[str, Any], experiment: Any) -> str:
    parameters = _get(experiment, "parameters", {})
    parameters = {str(name).casefold(): value for name, value in parameters.items()} if isinstance(parameters, Mapping) else {}
    for name, expected in conditions.get("parameters", {}).items():
        actual = parse_spice_number(str(parameters[name])) if name in parameters else None
        expected_number = parse_spice_number(expected)
        if actual is None:
            return f"Condition parameter {name} is not recorded in the experiment overrides"
        if not math.isclose(actual, expected_number, rel_tol=1e-12, abs_tol=0.0):
            return f"Condition parameter {name} does not match the experiment"
    if "temperature" in conditions:
        actual = _finite(_get(experiment, "temperature"))
        if actual is None:
            return "Condition temperature is not recorded in the experiment overrides"
        if not math.isclose(actual, conditions["temperature"], rel_tol=0.0, abs_tol=1e-9):
            return "Condition temperature does not match the experiment"
    return ""


def _measurement_unit(name: str, statement: str) -> str:
    """Use metadata only for unambiguous operations, never a vector prefix guess."""
    if not isinstance(statement, str):
        return ""
    tokens = tokenize_spice_directive(statement)
    if len(tokens) < 5 or tokens[0].casefold() not in {".measure", ".meas"} or tokens[2].casefold() != name.casefold():
        return ""
    operation = tokens[3].upper()
    if operation not in {"TRIG", "WHEN", "MIN_AT", "MAX_AT"}:
        if operation not in {"FIND", "MAX", "MIN", "AVG", "RMS", "PP", "INTEG", "INTEGRAL", "DERIV", "DERIVATIVE"}:
            return ""
        if _SIMPLE_VECTOR.fullmatch(tokens[4]) is None:
            return ""
    return measure_metadata_resolver.resolve(name, statement=statement).unit


def _measurement(result: Any, metric: str) -> tuple[float | None, str, str]:
    measurements = _get(result, "measurements", None) or []
    if not isinstance(measurements, list):
        return None, "", "Native measurement data is invalid"
    matches = [item for item in measurements if str(_get(item, "name", "")).casefold() == metric.casefold()]
    if len(matches) != 1:
        return None, "", "Native measurement is missing" if not matches else "Native measurement identity is ambiguous"
    measure = matches[0]
    status = _get(measure, "status")
    if _get(status, "value", status) != "OK":
        return None, "", _get(measure, "error_message", "") or "Native measurement failed or could not be parsed"
    value = _finite(_get(measure, "value"))
    if value is None:
        return None, "", "Native measurement did not produce a finite numeric value"
    return value, _measurement_unit(metric, _get(measure, "statement", "")), ""


def _op_signal(result: Any, metric: str) -> tuple[float | None, str, str]:
    if str(_get(result, "analysis_type", "")).casefold() != "op":
        return None, "", "Operating-point signal constraints require an OP analysis"
    # The shared trace service supplies canonical native signal identity and units.
    from domain.simulation.data.trace_analysis_service import trace_analysis_service

    try:
        table = trace_analysis_service.table(result, [{"signal": metric}], limit=1)
    except (ValueError, TypeError, AttributeError) as exc:
        return None, "", str(exc)
    if table["total_rows"] != 1 or not table["rows"]:
        return None, "", "Operating-point signal must contain exactly one native sample"
    value = _finite(table["rows"][0]["values"][0])
    if value is None:
        return None, "", "Operating-point signal did not produce a finite numeric value"
    return value, table["columns"][0]["unit"], ""


def _unit_parts(unit: str) -> tuple[str, float]:
    unit = _UNIT_ALIASES.get(unit, unit)
    if unit == "°":
        return "rad", math.pi / 180.0
    if unit in _PREFIXABLE:
        return unit, 1.0
    if len(unit) > 1 and unit[0] in _PREFIXES and unit[1:] in _PREFIXABLE:
        return unit[1:], _PREFIXES[unit[0]]
    return unit, 1.0


def convert_metric_value(value: Any, observed_unit: str, target_unit: str) -> tuple[float | None, str]:
    """Convert a finite scalar only between known, dimension-compatible units.

    Native dimensions must first be established by the caller. This shares the
    same prefix/phase semantics between acceptance and numerical comparisons.
    """
    number = _finite(value)
    if number is None:
        return None, "Native metric did not produce a finite numeric value"
    if not observed_unit or not target_unit:
        return None, "Native metric unit cannot be established from the result; no dimensional assumption was made"
    native_dimension, native_scale = _unit_parts(observed_unit)
    target_dimension, target_scale = _unit_parts(target_unit)
    if native_dimension != target_dimension:
        return None, f"Unit mismatch: native {observed_unit}, constraint {target_unit}"
    converted = number * (native_scale / target_scale)
    if not math.isfinite(converted):
        return None, "Unit conversion did not produce a finite numeric value"
    return converted, ""


def resolve_native_measurement(result: Any, metric: str) -> tuple[float | None, str, str]:
    """Return a finite, dimensionally established native measure or a reason.

    The value remains in ``native_unit``. Unlike display metadata, this rejects
    ambiguous PARAM/arithmetic dimensions, failed runs and unsuccessful measures;
    callers can safely exclude null values from corner/stability summaries.
    """
    if not _get(result, "success", False):
        return None, "", "Simulation did not complete successfully"
    value, unit, reason = _measurement(result, metric)
    if not reason and not unit:
        return None, "", "Native metric unit cannot be established from the result; no dimensional assumption was made"
    return value, unit, reason


def evaluate_acceptance(result: Any, experiment: Any) -> dict[str, Any]:
    """Return PASS/FAIL/NOT_MEASURED rows from the supplied frozen experiment.

    A failed/missing/nonfinite metric, incompatible/unknown unit, unrecorded
    condition, or failed run cannot pass. ``value`` and ``margin`` are null
    whenever a numeric comparison cannot be made. A negative margin means the
    nearest bound is violated, in the requested unit. FAIL takes precedence in
    the overall status; otherwise any unmeasured row prevents PASS.
    """
    constraints = validate_acceptance_constraints(_get(experiment, "acceptance_constraints", []))
    rows = []
    counts = {"PASS": 0, "FAIL": 0, "NOT_MEASURED": 0}
    for constraint in constraints:
        row = {**constraint, "status": "NOT_MEASURED", "value": None,
               "observed_unit": "", "reason": "", "margin": None}
        reason = _condition_reason(constraint["conditions"], experiment)
        if not reason and not _get(result, "success", False):
            reason = "Simulation did not complete successfully"
        if not reason:
            value, unit, reason = (_measurement if constraint["source"] == "measurement" else _op_signal)(result, constraint["metric"])
            row["observed_unit"] = unit
            if not reason:
                value, reason = convert_metric_value(value, unit, constraint["unit"])
            if not reason:
                lower, upper = constraint["lower"], constraint["upper"]
                margins = ([value - lower] if lower is not None else []) + ([upper - value] if upper is not None else [])
                margin = min(margins)
                passed = (lower is None or value >= lower) and (upper is None or value <= upper)
                row.update(value=value, margin=margin if math.isfinite(margin) else None,
                           status="PASS" if passed else "FAIL")
                reason = "Within inclusive limits" if passed else "Outside inclusive limits"
        row["reason"] = reason
        counts[row["status"]] += 1
        rows.append(row)
    status = "FAIL" if counts["FAIL"] else "NOT_MEASURED" if counts["NOT_MEASURED"] or not rows else "PASS"
    return {"status": status, "rows": rows, "counts": counts}


__all__ = ["validate_acceptance_constraints", "evaluate_acceptance",
           "resolve_native_measurement", "convert_metric_value"]
