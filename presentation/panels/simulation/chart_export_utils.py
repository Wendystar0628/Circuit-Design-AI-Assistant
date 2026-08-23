from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from domain.simulation.data.downsampler import (
    align_xy,
    crop_to_viewport,
    downsample_preserving_gaps,
)
from domain.simulation.data.simulation_artifact_exporter import simulation_artifact_exporter
from domain.simulation.data.signal_semantics import (
    nested_dc_secondary_values,
    parse_nested_dc_sweep,
)
from domain.simulation.models.simulation_result import SimulationResult
from presentation.panels.simulation.chart_view_types import ChartSeries, ChartSpec


def serialize_chart_series(series: ChartSeries) -> Dict[str, Any]:
    x_data, y_data = align_xy(series.x_data, series.y_data)
    return {
        "name": series.name,
        "color": series.color,
        "axis_key": series.axis_key,
        "axis_family": series.axis_family,
        "line_style": series.line_style,
        "group_key": series.group_key,
        "component": series.component,
        "x": _nullable_values(x_data),
        "y": _nullable_values(y_data),
        "point_count": len(y_data),
    }


def serialize_chart_series_for_web(
    series: ChartSeries,
    *,
    max_points: int = 800,
    x_range: Optional[Tuple[float, float]] = None,
) -> Dict[str, Any]:
    x_data, y_data = align_xy(series.x_data, series.y_data)
    total_points = len(x_data)
    if x_range is not None:
        x_data, y_data = crop_to_viewport(
            x_data,
            y_data,
            x_range[0],
            x_range[1],
        )
    if max_points > 1 and total_points > max_points:
        x_sample, y_sample = downsample_preserving_gaps(x_data, y_data, max_points)
    else:
        x_sample, y_sample = x_data, y_data
    return {
        "name": series.name,
        "color": series.color,
        "axis_key": series.axis_key,
        "axis_family": series.axis_family,
        "line_style": series.line_style,
        "group_key": series.group_key,
        "component": series.component,
        "x": _nullable_values(x_sample),
        "y": _nullable_values(y_sample),
        "point_count": total_points,
        "sampled_point_count": len(y_sample),
    }


def build_chart_data_rows(
    x_label: str,
    series_list: Sequence[ChartSeries],
) -> List[Dict[str, Any]]:
    """Build a wide table on a real shared X grid.

    Series that already share an X vector remain byte-for-byte aligned.  If
    inputs differ, their finite coordinates are merged and every signal is
    emitted only at coordinates actually produced by the simulator.  Export is
    evidence, so it must not invent intermediate samples merely to make a wide
    CSV look dense.
    """

    prepared: List[Tuple[ChartSeries, np.ndarray, np.ndarray]] = []
    for series in series_list:
        x_data, y_data = align_xy(series.x_data, series.y_data)
        if np.any(np.isfinite(x_data)):
            prepared.append((series, x_data, y_data))
    if not prepared:
        return []

    reference_x = max(prepared, key=lambda item: len(item[1]))[1]
    shared_traversal = all(
        len(x_data) <= len(reference_x)
        and np.array_equal(x_data, reference_x[:len(x_data)], equal_nan=True)
        for _, x_data, _ in prepared
    )
    if shared_traversal:
        x_grid = reference_x.copy()
    else:
        finite_coordinate_sets = [
            item[1][np.isfinite(item[1])]
            for item in prepared
            if np.any(np.isfinite(item[1]))
        ]
        x_grid = _merged_coordinate_grid(finite_coordinate_sets)
    columns: Dict[str, np.ndarray] = {}
    for series, x_data, y_data in prepared:
        if shared_traversal:
            values = np.full(len(x_grid), np.nan, dtype=float)
            values[:len(y_data)] = y_data
        else:
            finite_x = np.isfinite(x_data)
            values = _values_on_grid(x_grid, x_data[finite_x], y_data[finite_x])
        columns[series.name] = values
    rows: List[Dict[str, Any]] = []
    for index, x_value in enumerate(x_grid):
        if not np.isfinite(x_value):
            rows.append({x_label: None})
            continue
        row: Dict[str, Any] = {x_label: float(x_value)}
        for series, _, _ in prepared:
            value = columns[series.name][index]
            if np.isfinite(value):
                row[series.name] = float(value)
        rows.append(row)
    return rows


def add_nested_dc_secondary_column(
    rows: List[Dict[str, Any]],
    x_label: str,
    result: SimulationResult,
) -> Optional[str]:
    """Add the outer DC source value to every flattened branch row."""

    sweep = parse_nested_dc_sweep(result.analysis_type, result.analysis_command)
    if sweep is None or not rows:
        return None
    x_values = []
    for row in rows:
        try:
            value = float(row.get(x_label))
        except (TypeError, ValueError, OverflowError):
            value = np.nan
        x_values.append(value if np.isfinite(value) else np.nan)
    secondary_values = nested_dc_secondary_values(np.asarray(x_values, dtype=float), sweep)
    if not np.any(np.isfinite(secondary_values)):
        return None
    label = sweep.secondary_column_label
    for row, value in zip(rows, secondary_values):
        if np.isfinite(value):
            row[label] = float(value)
    return label


def enrich_chart_export_with_nested_dc(
    export_payload: Dict[str, Any],
    result: SimulationResult,
) -> None:
    """Make the branch coordinate explicit in chart JSON and CSV exports."""

    x_label = str(export_payload.get("x_label") or "X")
    label = add_nested_dc_secondary_column(export_payload.get("rows", []), x_label, result)
    if label is None:
        return
    sweep = parse_nested_dc_sweep(result.analysis_type, result.analysis_command)
    if sweep is None:
        return
    export_payload["secondary_sweep_label"] = label
    export_payload["secondary_sweep"] = {
        "source_name": sweep.secondary_source,
        "start_value": sweep.secondary_start,
        "stop_value": sweep.secondary_stop,
        "step": sweep.secondary_step,
        "unit": sweep.secondary_unit,
    }


def _merged_coordinate_grid(coordinate_sets: Sequence[np.ndarray]) -> np.ndarray:
    """Merge exact coordinates without reversing a descending sweep."""

    concatenated = np.concatenate(coordinate_sets)
    primary = coordinate_sets[0]
    primary_differences = np.diff(primary)
    if len(primary) > 1 and np.all(primary_differences < 0):
        return np.unique(concatenated)[::-1]
    if len(primary) <= 1 or np.all(primary_differences > 0):
        return np.unique(concatenated)

    # Nested/non-monotonic sweeps cannot be faithfully flattened onto a
    # coordinate-keyed wide table.  Preserve first traversal order and never
    # synthesize values; repeated coordinates remain a documented P2 boundary.
    ordered = list(dict.fromkeys(float(value) for value in concatenated))
    return np.asarray(ordered, dtype=float)


def _values_on_grid(x_grid: np.ndarray, x_data: np.ndarray, y_data: np.ndarray) -> np.ndarray:
    values = np.full(len(x_grid), np.nan, dtype=float)
    exact_values = {float(x): float(y) for x, y in zip(x_data, y_data)}
    for index, x_value in enumerate(x_grid):
        if float(x_value) in exact_values:
            values[index] = exact_values[float(x_value)]
    return values


def _nullable_values(values: np.ndarray) -> List[Optional[float]]:
    return [float(value) if np.isfinite(value) else None for value in values]


def build_chart_export_payload(
    spec: ChartSpec,
    visible_series: Sequence[ChartSeries],
) -> Dict[str, Any]:
    rows = build_chart_data_rows(spec.x_label, visible_series)
    return {
        "chart_type": spec.chart_type.value,
        "title": spec.title,
        "x_label": spec.x_label,
        "y_label": spec.y_label,
        "secondary_y_label": spec.secondary_y_label,
        "log_x": spec.log_x,
        "log_y": spec.log_y,
        "right_log_y": spec.right_log_y,
        "series": [serialize_chart_series(series) for series in visible_series],
        "rows": rows,
    }


def write_chart_csv(
    path: str,
    export_payload: Dict[str, Any],
    result: SimulationResult,
) -> bool:
    rows = export_payload.get("rows", [])
    headers = [export_payload["x_label"]]
    secondary_sweep_label = export_payload.get("secondary_sweep_label")
    if secondary_sweep_label:
        headers.append(str(secondary_sweep_label))
    headers += [
        series["name"] for series in export_payload.get("series", [])
    ]
    simulation_artifact_exporter.write_csv_with_header(
        path,
        result,
        "chart",
        headers,
        rows,
    )
    return True


__all__ = [
    "add_nested_dc_secondary_column",
    "build_chart_data_rows",
    "build_chart_export_payload",
    "enrich_chart_export_with_nested_dc",
    "serialize_chart_series",
    "serialize_chart_series_for_web",
    "write_chart_csv",
]
