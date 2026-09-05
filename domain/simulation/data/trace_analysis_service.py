"""One numerical contract for simulation traces, tables, cursors and exports.

Native simulator vectors stay authoritative. TraceSpec describes a projection
of those vectors; render decimation never becomes an input to measurements.
DC branch identity belongs to raw rows. Only rendered lines contain separators.
"""

from __future__ import annotations

import csv
import io
import json
import math
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

import numpy as np

from domain.simulation.data.downsampler import downsample, viewport_indexes
from domain.simulation.data.signal_semantics import (
    nested_dc_reset_indexes,
    nested_dc_secondary_values,
    normalize_simulation_signal_name,
    parse_device_parameter_signal_name,
    parse_nested_dc_sweep,
    resolve_device_parameter_unit,
    resolve_signal_type,
)
from domain.simulation.models.simulation_result import SimulationResult


_COMPONENTS = ("real", "imaginary", "magnitude", "db", "phase")
_MAX_TRACES = 16
_MAX_POINTS = 20000


@dataclass(frozen=True)
class TraceSpec:
    signal: str
    reference: str | None = None
    component: str = "real"

    @classmethod
    def parse(cls, value: TraceSpec | Mapping[str, Any]) -> TraceSpec:
        if isinstance(value, cls):
            value = asdict(value)
        if not isinstance(value, Mapping):
            raise ValueError("Each trace must be an object")
        unknown = set(value) - {"signal", "reference", "component"}
        if unknown:
            raise ValueError(f"Unknown trace fields: {', '.join(sorted(unknown))}")
        signal = value.get("signal")
        reference = value.get("reference")
        component = value.get("component", "real")
        if not isinstance(signal, str) or not signal.strip():
            raise ValueError("A trace requires a native signal name")
        if reference is not None and (not isinstance(reference, str) or not reference.strip()):
            raise ValueError("A reference must be a native signal name or null")
        if component not in _COMPONENTS:
            raise ValueError(f"Unsupported trace component: {component!r}")
        return cls(signal.strip(), reference.strip() if reference else None, component)


@dataclass
class _Context:
    x: np.ndarray
    axis: dict[str, str]
    branch_ids: np.ndarray
    outer_values: np.ndarray
    branches: list[dict[str, Any]]


@dataclass
class _Trace:
    spec: TraceSpec
    y: np.ndarray
    unit: str
    label: str

    @property
    def id(self) -> str:
        return json.dumps(asdict(self.spec), ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    def metadata(self) -> dict[str, Any]:
        return {"id": self.id, "trace": asdict(self.spec), "label": self.label, "unit": self.unit}


class TraceAnalysisService:
    """Pure, stateless engineering views over a validated SimulationResult."""

    def catalog(self, result: SimulationResult) -> dict[str, Any]:
        if result is None or not result.success or result.data is None:
            return {"x_axis": {"kind": "none", "label": "", "unit": "", "scale": "linear"},
                    "signals": [], "branches": [], "default_traces": []}
        context = self._context(result)
        assert result.data is not None
        signals = []
        for name, values in result.data.signals.items():
            unit = self._native_unit(result, name)
            complex_values = bool(np.iscomplexobj(values))
            components = ["real", "magnitude"]
            if complex_values:
                components = ["real", "imaginary", "magnitude", "phase"]
                if unit in {"V", "A"}:
                    components.insert(3, "db")
            signals.append({
                "name": name,
                "unit": unit,
                "signal_type": resolve_signal_type(name, result.data.signal_types),
                "is_complex": complex_values,
                "components": components,
            })
        signals.sort(key=lambda item: ("out" not in item["name"].lower(), item["name"].casefold()))
        default = []
        if signals:
            selected = signals[0]
            component = "db" if "db" in selected["components"] else "magnitude" if selected["is_complex"] else "real"
            default.append(asdict(TraceSpec(selected["name"], component=component)))
            if selected["is_complex"]:
                default.append(asdict(TraceSpec(selected["name"], component="phase")))
        return {"x_axis": context.axis, "signals": signals, "branches": context.branches, "default_traces": default}

    def query(
        self, result: SimulationResult, traces: Sequence[TraceSpec | Mapping[str, Any]],
        x_min: float | None = None, x_max: float | None = None, max_points: int = 1200,
    ) -> dict[str, Any]:
        max_points = _integer(max_points, "max_points", 2, _MAX_POINTS)
        context = self._context(result)
        prepared = self._traces(result, traces, context)
        lower, upper = _window(context.x, x_min, x_max)
        inside = (context.x >= lower) & (context.x <= upper)
        series = []
        for trace in prepared:
            runs = self._visible_runs(context, trace.y, lower, upper)
            minimums = [len(_essential_indexes(trace.y[run])) for run in runs]
            minimum = sum(minimums) + max(0, len(runs) - 1)
            if minimum > max_points:
                raise ValueError(
                    f"This viewport needs at least {minimum} points to preserve every branch, extremum and gap; "
                    "increase max_points or narrow the viewport"
                )
            targets = _allocate_points([len(run) for run in runs], minimums, max_points)
            out_x: list[float | None] = []
            out_y: list[float | None] = []
            out_branches: list[int | None] = []
            native_visible = sum(len(run) for run in runs)
            for index, (run, target) in enumerate(zip(runs, targets)):
                x, y = _screen_envelope(context.x[run], trace.y[run], target, context.axis["scale"])
                if index:
                    out_x.append(None)
                    out_y.append(None)
                    out_branches.append(None)
                out_x.extend(float(value) for value in x)
                out_y.extend(float(value) for value in y)
                out_branches.extend([int(context.branch_ids[run[0]])] * len(x))
            finite_rendered = sum(value is not None for value in out_y)
            series.append({
                **trace.metadata(), "x": out_x, "y": out_y, "branch_ids": out_branches,
                "branches": context.branches, "raw_point_count": len(context.x),
                "visible_point_count": native_visible, "point_count": len(out_x),
                "invalid_sample_count": int(np.count_nonzero(inside & ~np.isfinite(trace.y))),
                "downsampled": finite_rendered < native_visible,
            })
        return {
            "x_axis": context.axis, "window": {"x_min": lower, "x_max": upper},
            "series": series, "max_points": max_points,
            "decimation": "screen-space min/max envelope; native order and every finite run retained",
        }

    def table(
        self, result: SimulationResult, traces: Sequence[TraceSpec | Mapping[str, Any]],
        offset: int = 0, limit: int = 200,
    ) -> dict[str, Any]:
        offset = _integer(offset, "offset", 0)
        limit = _integer(limit, "limit", 1, 2000)
        context = self._context(result)
        prepared = self._traces(result, traces, context)
        rows = [{
            "index": index, "x": float(context.x[index]),
            "branch_id": int(context.branch_ids[index]),
            "outer_value": _finite(context.outer_values[index]),
            "values": [_finite(trace.y[index]) for trace in prepared],
        } for index in range(min(offset, len(context.x)), min(offset + limit, len(context.x)))]
        return {
            "x_axis": context.axis, "columns": [trace.metadata() for trace in prepared],
            "branches": context.branches, "rows": rows, "total_rows": len(context.x),
            "offset": offset, "limit": limit,
        }

    def measure(
        self, result: SimulationResult, traces: Sequence[TraceSpec | Mapping[str, Any]],
        x_min: float | None = None, x_max: float | None = None,
        cursor_a: float | None = None, cursor_b: float | None = None,
    ) -> dict[str, Any]:
        context = self._context(result)
        prepared = self._traces(result, traces, context)
        lower, upper = _window(context.x, x_min, x_max)
        for name, value in (("cursor_a", cursor_a), ("cursor_b", cursor_b)):
            if value is not None:
                _number(value, name)
        measurements = []
        for trace in prepared:
            for branch in context.branches:
                branch_mask = context.branch_ids == branch["id"]
                x, y = context.x[branch_mask], trace.y[branch_mask]
                sample_mask = (x >= lower) & (x <= upper) & np.isfinite(y)
                sample_y = y[sample_mask]
                # Clipped linear segments define the requested physical window,
                # including boundary values even when no native sample lies inside.
                clipped = _clipped_segments(x, y, lower, upper)
                minima = [float(np.min(sample_y))] if len(sample_y) else []
                maxima = [float(np.max(sample_y))] if len(sample_y) else []
                if len(clipped):
                    minima.append(float(np.min(clipped[:, 2:])))
                    maxima.append(float(np.max(clipped[:, 2:])))
                minimum, maximum = (min(minima), max(maxima)) if minima else (None, None)
                duration = float(np.sum(clipped[:, 1] - clipped[:, 0]))
                mean = rms = None
                native_time_trace = context.axis["kind"] == "time" and trace.spec.component == "real" and trace.spec.reference is None
                if native_time_trace and duration > 0:
                    mean, rms = _time_moments(clipped, duration)
                a = _cursor(x, y, cursor_a)
                b = _cursor(x, y, cursor_b)
                delta_x = float(cursor_b - cursor_a) if cursor_a is not None and cursor_b is not None else None
                delta_y = b["y"] - a["y"] if a and b and a["y"] is not None and b["y"] is not None else None
                coverage = max(0.0, min(upper, float(np.max(x))) - max(lower, float(np.min(x))))
                measurements.append({
                    **trace.metadata(), "branch_id": branch["id"], "outer_value": branch["outer_value"],
                    "sample_count": int(len(sample_y)), "min": minimum, "max": maximum,
                    "peak_to_peak": _finite(maximum - minimum) if minimum is not None else None,
                    "sample_mean": _stable_mean(sample_y), "time_mean": _finite(mean), "time_rms": _finite(rms),
                    "duration": duration if context.axis["kind"] == "time" else None,
                    "coverage_fraction": min(1.0, duration / coverage) if coverage > 0 else None,
                    "cursor_a": a, "cursor_b": b, "delta_x": _finite(delta_x), "delta_y": _finite(delta_y),
                    "slope": _finite(delta_y / delta_x) if delta_y is not None and delta_x else None,
                    "statistics_basis": (
                        "time-weighted piecewise-linear native waveform" if native_time_trace else
                        "derived samples only; physical time mean and RMS require an unreferenced real transient trace"
                        if context.axis["kind"] == "time" else "native samples; no physical time average"
                    ),
                })
        return {
            "x_axis": context.axis, "window": {"x_min": lower, "x_max": upper}, "measurements": measurements,
            "method": "Raw derived samples; cursors interpolate linearly in native x without crossing gaps or DC branches. "
            "Only unreferenced real transient traces provide physical time mean and RMS. These integrate "
            "the native piecewise-linear waveform, including clipped window boundaries; "
            "RMS integrates its squared linear segments exactly. Other analyses report sample statistics only.",
        }

    def export_csv(self, result: SimulationResult, traces: Sequence[TraceSpec | Mapping[str, Any]]) -> str:
        """Export every raw row using exactly the same trace derivation as the UI."""
        context = self._context(result)
        prepared = self._traces(result, traces, context)
        output = io.StringIO(newline="")
        for key, value in (
            ("file_path", result.file_path), ("source_digest", result.source_digest),
            ("analysis_command", result.analysis_command), ("timestamp", result.timestamp),
            ("trace_specs", [asdict(trace.spec) for trace in prepared]),
            ("sampling", "full resolution native rows; no render separators or decimation"),
        ):
            output.write(f"# {key}: {json.dumps(value, ensure_ascii=False)}\n")
        writer = csv.writer(output, lineterminator="\n")
        writer.writerow(["sample_index", context.axis["label"], "branch_id", "outer_sweep", *[
            f"{trace.label} [{trace.unit}]" if trace.unit else trace.label for trace in prepared
        ]])
        for index, x in enumerate(context.x):
            writer.writerow([
                index, _csv_number(x), int(context.branch_ids[index]), _csv_number(context.outer_values[index]),
                *[_csv_number(trace.y[index]) for trace in prepared],
            ])
        return output.getvalue()

    def _context(self, result: SimulationResult) -> _Context:
        if result is None or not result.success or result.data is None:
            raise ValueError("Trace analysis requires a successful simulation with native data")
        raw_x = result.get_x_axis_data()
        x = np.asarray(raw_x if raw_x is not None else [0.0], dtype=float)
        if x.ndim != 1 or len(x) == 0 or not np.all(np.isfinite(x)):
            raise ValueError("The native x axis must be one-dimensional, non-empty and finite")
        kind = result.x_axis_kind
        unit = {"time": "s", "frequency": "Hz"}.get(kind, "")
        if kind == "sweep":
            label = result.get_x_axis_label()
            unit = next((candidate for candidate in ("V", "A", "Ω", "°C") if label.endswith(f"({candidate})")), "")
        label = result.get_x_axis_label()
        if unit and label.endswith(f" ({unit})"):
            label = label[:-(len(unit) + 3)]
        axis = {"kind": kind, "label": label, "unit": unit,
                "scale": "log" if result.is_x_axis_log() else "linear"}
        branch_ids = np.zeros(len(x), dtype=np.int64)
        outer = np.full(len(x), np.nan)
        branches = [{"id": 0, "label": "Run", "outer_value": None, "outer_unit": ""}]
        sweep = parse_nested_dc_sweep(result.analysis_type, result.analysis_command)
        if sweep is not None:
            resets = nested_dc_reset_indexes(x, sweep)
            branch_ids[resets] = 1
            branch_ids = np.cumsum(branch_ids)
            outer = nested_dc_secondary_values(x, sweep)
            branches = []
            for branch_id in np.unique(branch_ids):
                indexes = np.flatnonzero(branch_ids == branch_id)
                value = _finite(outer[indexes[0]])
                branches.append({"id": int(branch_id), "label": f"{sweep.secondary_source} = {value:g} {sweep.secondary_unit}" if value is not None else f"Branch {branch_id}",
                                 "outer_value": value, "outer_unit": sweep.secondary_unit})
        return _Context(x, axis, branch_ids, outer, branches)

    def _traces(self, result: SimulationResult, traces: Sequence[TraceSpec | Mapping[str, Any]], context: _Context) -> list[_Trace]:
        if isinstance(traces, (str, bytes)) or not isinstance(traces, Sequence) or not 1 <= len(traces) <= _MAX_TRACES:
            raise ValueError(f"Select between 1 and {_MAX_TRACES} traces")
        prepared = [self._derive(result, TraceSpec.parse(value), context) for value in traces]
        if len({trace.id for trace in prepared}) != len(prepared):
            raise ValueError("Duplicate traces are not allowed")
        return prepared

    def _derive(self, result: SimulationResult, spec: TraceSpec, context: _Context) -> _Trace:
        assert result.data is not None
        signal = self._resolve_name(result, spec.signal)
        reference = self._resolve_name(result, spec.reference) if spec.reference else None
        spec = TraceSpec(signal, reference, spec.component)
        values = np.asarray(result.data.signals[signal])
        if values.ndim != 1 or len(values) != len(context.x):
            raise ValueError(f"Native signal {signal!r} does not align with the x axis")
        native_unit = self._native_unit(result, signal)
        unit = native_unit
        if reference:
            denominator = np.asarray(result.data.signals[reference])
            if denominator.shape != values.shape:
                raise ValueError("Trace and reference must share the native x axis")
            reference_unit = self._native_unit(result, reference)
            same_dimension = bool(native_unit) and native_unit == reference_unit
            unit = "1" if same_dimension else {("V", "A"): "Ω", ("A", "V"): "S"}.get((native_unit, reference_unit), "")
            if not unit and native_unit and reference_unit:
                unit = f"{native_unit}/({reference_unit})"
            quotient = np.full(values.shape, np.nan + 0j if np.iscomplexobj(values) else np.nan,
                               dtype=complex if np.iscomplexobj(values) else float)
            valid = np.isfinite(values) & np.isfinite(denominator) & (np.abs(denominator) > 0)
            with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
                np.divide(values, denominator, out=quotient, where=valid)
            values = quotient
        component = spec.component
        if component in {"phase", "imaginary", "db"} and result.analysis_type != "ac":
            raise ValueError(f"{component} traces require complex AC data")
        if component in {"phase", "imaginary", "db"} and not np.iscomplexobj(values):
            raise ValueError(f"{component} traces require native complex samples")
        if component == "db":
            if reference:
                if not (native_unit and native_unit == self._native_unit(result, reference)):
                    raise ValueError("dB ratios require numerator and reference with the same known physical dimension")
                unit = "dB"
            else:
                if native_unit not in {"V", "A"}:
                    raise ValueError("Absolute dB traces require a known V or A reference unit")
                unit = "dBV" if native_unit == "V" else "dBA"
        elif component == "phase":
            unit = "°"
        y = project_trace_values(values, component, context.branch_ids)
        expression = f"{signal} / {reference}" if reference else signal
        title = {"real": "Real", "imaginary": "Imaginary", "magnitude": "Magnitude", "db": "Level", "phase": "Phase"}[component]
        label = f"{expression} · {title}" if np.iscomplexobj(values) or reference or component != "real" else expression
        return _Trace(spec, y, unit, label)

    @staticmethod
    def _resolve_name(result: SimulationResult, name: str) -> str:
        assert result.data is not None
        if name in result.data.signals:
            return name
        normalized = normalize_simulation_signal_name(name).casefold()
        matches = [candidate for candidate in result.data.signals if candidate.casefold() == normalized]
        if len(matches) != 1:
            raise ValueError(f"Unknown native signal: {name!r}")
        return matches[0]

    @staticmethod
    def _native_unit(result: SimulationResult, name: str) -> str:
        assert result.data is not None
        device = parse_device_parameter_signal_name(name)
        if device is not None:
            explicit = resolve_device_parameter_unit(device[1])
            if explicit:
                return explicit
        unit = {"voltage": "V", "current": "A"}.get(resolve_signal_type(name, result.data.signal_types), "")
        return f"{unit}/√Hz" if unit and result.analysis_type == "noise" else unit

    @staticmethod
    def _visible_runs(context: _Context, y: np.ndarray, lower: float, upper: float) -> list[np.ndarray]:
        result = []
        for start, stop in _runs(np.isfinite(y), context.branch_ids):
            indexes = viewport_indexes(context.x[start:stop], lower, upper)
            if indexes.size:
                result.append(indexes + start)
        return result


def _integer(value: Any, name: str, minimum: int, maximum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum or (maximum is not None and value > maximum):
        raise ValueError(f"{name} must be an integer from {minimum}" + (f" to {maximum}" if maximum is not None else " upward"))
    return value


def project_trace_values(values: np.ndarray, component: str, branch_ids: np.ndarray | None = None) -> np.ndarray:
    """Shared numeric projection for workbench and existing artifact readers.

    Callers establish physical units before requesting dB. A zero complex
    value has no phase or logarithmic level and remains an explicit gap.
    """
    values = np.asarray(values)
    if values.ndim != 1 or component not in _COMPONENTS:
        raise ValueError("Trace projection requires a one-dimensional vector and known component")
    branches = np.zeros(len(values), dtype=np.int64) if branch_ids is None else branch_ids
    if component == "db":
        magnitude = np.abs(values)
        y = np.full(values.shape, np.nan)
        valid = np.isfinite(magnitude) & (magnitude > 0)
        y[valid] = 20.0 * np.log10(magnitude[valid])
    elif component == "phase":
        y = np.full(values.shape, np.nan)
        valid = np.isfinite(values) & (np.abs(values) > 0)
        for start, stop in _runs(valid, branches):
            y[start:stop] = np.degrees(np.unwrap(np.angle(values[start:stop])))
    elif component == "magnitude":
        y = np.abs(values)
    elif component == "imaginary":
        y = np.imag(values)
    else:
        y = np.real(values)
    y = np.asarray(y, dtype=float).copy()
    y[~np.isfinite(values) | ~np.isfinite(y)] = np.nan
    return y


def _number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ValueError(f"{name} must be a finite number")
    return float(value)


def _window(x: np.ndarray, lower: float | None, upper: float | None) -> tuple[float, float]:
    lower = float(np.min(x)) if lower is None else _number(lower, "x_min")
    upper = float(np.max(x)) if upper is None else _number(upper, "x_max")
    if lower > upper:
        raise ValueError("x_min must not exceed x_max")
    return lower, upper


def _runs(valid: np.ndarray, branch_ids: np.ndarray) -> list[tuple[int, int]]:
    # A branch change is a discontinuity even when adjacent x/y are finite.
    if len(valid) == 0:
        return []
    starts = np.flatnonzero(valid & np.concatenate(([True], ~valid[:-1] | (np.diff(branch_ids) != 0))))
    stops = np.flatnonzero(valid & np.concatenate((~valid[1:] | (np.diff(branch_ids) != 0), [True]))) + 1
    return [(int(start), int(stop)) for start, stop in zip(starts, stops)]


def _allocate_points(lengths: list[int], minimums: list[int], budget: int) -> list[int]:
    if not lengths:
        return []
    targets = np.asarray(minimums, dtype=np.int64)
    spare = budget - (len(lengths) - 1) - int(np.sum(targets))
    needs = np.asarray(lengths) - targets
    if spare > 0 and np.sum(needs) > 0:
        allocation = np.minimum(needs, np.floor(needs / np.sum(needs) * spare)).astype(np.int64)
        targets += allocation
        spare -= int(np.sum(allocation))
        # At most one remainder point per run after proportional allocation.
        for index in sorted(range(len(lengths)), key=lambda i: lengths[i] - targets[i], reverse=True):
            if spare <= 0:
                break
            if targets[index] < lengths[index]:
                targets[index] += 1
                spare -= 1
    return [int(value) for value in targets]


def _screen_envelope(x: np.ndarray, y: np.ndarray, target: int, scale: str) -> tuple[np.ndarray, np.ndarray]:
    if len(x) <= target:
        return x, y
    if target <= 3:
        selected = _essential_indexes(y)
        return x[selected], y[selected]
    mapped = np.log10(x) if scale == "log" and np.all(x > 0) else x
    low, high = float(np.min(mapped)), float(np.max(mapped))
    if low == high:
        return downsample(x, y, target)
    buckets = max(1, (target - 2) // 2)
    ids = np.minimum(buckets - 1, np.floor((mapped[1:-1] - low) / (high - low) * buckets)).astype(np.int64)
    boundaries = np.concatenate(([0], np.flatnonzero(np.diff(ids) != 0) + 1, [len(ids)]))
    selected = [0]
    for start, stop in zip(boundaries[:-1], boundaries[1:]):
        indexes = np.arange(int(start) + 1, int(stop) + 1)
        if len(indexes):
            selected.extend(sorted({int(indexes[np.argmin(y[indexes])]), int(indexes[np.argmax(y[indexes])])}))
    selected.append(len(x) - 1)
    return x[selected], y[selected]


def _essential_indexes(y: np.ndarray) -> list[int]:
    return sorted({0, len(y) - 1, int(np.argmin(y)), int(np.argmax(y))})


def _cursor(x: np.ndarray, y: np.ndarray, requested: float | None) -> dict[str, Any] | None:
    if requested is None:
        return None
    if len(x) > 1 and x[-1] < x[0]:
        x, y = x[::-1], y[::-1]
    value = float(requested)
    base = {"x": value, "y": None, "interpolated": False, "status": "outside"}
    right = int(np.searchsorted(x, value))
    if right < len(x) and x[right] == value:
        scalar = _finite(y[right])
        return {**base, "y": scalar, "status": "sample" if scalar is not None else "gap"}
    if right == 0 or right == len(x):
        return base
    left = right - 1
    if not np.isfinite(y[left]) or not np.isfinite(y[right]):
        return {**base, "status": "gap"}
    weight = (value - float(x[left])) / float(x[right] - x[left])
    scalar = _finite((1.0 - weight) * float(y[left]) + weight * float(y[right]))
    return {**base, "y": scalar, "interpolated": True, "status": "interpolated" if scalar is not None else "gap"}


def _clipped_segments(x: np.ndarray, y: np.ndarray, lower: float, upper: float) -> np.ndarray:
    if len(x) > 1 and x[-1] < x[0]:
        x, y = x[::-1], y[::-1]
    x0, x1, y0, y1 = x[:-1], x[1:], y[:-1], y[1:]
    valid = (x1 > x0) & (x1 > lower) & (x0 < upper) & np.isfinite(y0) & np.isfinite(y1)
    x0, x1, y0, y1 = x0[valid], x1[valid], y0[valid], y1[valid]
    left, right = np.maximum(x0, lower), np.minimum(x1, upper)
    positive = right > left
    left, right, x0, x1, y0, y1 = [array[positive] for array in (left, right, x0, x1, y0, y1)]
    w0, w1 = (left - x0) / (x1 - x0), (right - x0) / (x1 - x0)
    return np.column_stack((left, right, (1 - w0) * y0 + w0 * y1, (1 - w1) * y0 + w1 * y1))


def _time_moments(segments: np.ndarray, duration: float) -> tuple[float, float]:
    scale = float(np.max(np.abs(segments[:, 2:]))) if len(segments) else 0.0
    if scale == 0:
        return 0.0, 0.0
    weights = (segments[:, 1] - segments[:, 0]) / duration
    y0, y1 = segments[:, 2] / scale, segments[:, 3] / scale
    first = float(np.sum(weights * (y0 + y1) / 2))
    second = float(np.sum(weights * (y0 * y0 + y0 * y1 + y1 * y1) / 3))
    return scale * max(-1.0, min(1.0, first)), scale * math.sqrt(max(0.0, min(1.0, second)))


def _stable_mean(values: np.ndarray) -> float | None:
    if len(values) == 0:
        return None
    scale = float(np.max(np.abs(values)))
    return scale * math.fsum(float(value / scale) / len(values) for value in values) if scale else 0.0


def _finite(value: Any) -> float | None:
    if value is None:
        return None
    scalar = float(value)
    return scalar if math.isfinite(scalar) else None


def _csv_number(value: Any) -> str:
    scalar = _finite(value)
    return format(scalar, ".17g") if scalar is not None else ""


trace_analysis_service = TraceAnalysisService()

__all__ = ["TraceSpec", "TraceAnalysisService", "trace_analysis_service", "project_trace_values"]
