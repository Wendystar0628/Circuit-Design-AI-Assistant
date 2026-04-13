import csv
from typing import Any, Dict, List, Sequence
import numpy as np

from presentation.panels.simulation.chart_view_types import ChartSeries, ChartSpec


def serialize_chart_series(series: ChartSeries) -> Dict[str, Any]:
    return {
        "name": series.name,
        "color": series.color,
        "axis_key": series.axis_key,
        "line_style": series.line_style,
        "group_key": series.group_key,
        "component": series.component,
        "x": [float(value) for value in series.x_data],
        "y": [float(value) for value in series.y_data],
        "point_count": len(series.y_data),
    }


def serialize_chart_series_for_web(
    series: ChartSeries,
    *,
    max_points: int = 800,
) -> Dict[str, Any]:
    x_data = np.asarray(series.x_data, dtype=float)
    y_data = np.asarray(series.y_data, dtype=float)
    total_points = min(len(x_data), len(y_data))
    if total_points <= 0:
        x_values: List[float] = []
        y_values: List[float] = []
    else:
        if max_points > 0 and total_points > max_points:
            sample_indexes = np.linspace(0, total_points - 1, num=max_points, dtype=int)
            x_data = x_data[sample_indexes]
            y_data = y_data[sample_indexes]
        else:
            x_data = x_data[:total_points]
            y_data = y_data[:total_points]
        x_values = [float(value) for value in x_data]
        y_values = [float(value) for value in y_data]
    return {
        "name": series.name,
        "color": series.color,
        "axis_key": series.axis_key,
        "line_style": series.line_style,
        "group_key": series.group_key,
        "component": series.component,
        "x": x_values,
        "y": y_values,
        "point_count": total_points,
        "sampled_point_count": len(y_values),
    }


def build_chart_data_rows(x_label: str, series_list: Sequence[ChartSeries]) -> List[Dict[str, float]]:
    if not series_list:
        return []
    primary_x = series_list[0].x_data
    rows: List[Dict[str, float]] = []
    for index, x_value in enumerate(primary_x):
        row: Dict[str, float] = {x_label: float(x_value)}
        for series in series_list:
            if index < len(series.y_data):
                row[series.name] = float(series.y_data[index])
        rows.append(row)
    return rows


def build_chart_export_payload(spec: ChartSpec, visible_series: Sequence[ChartSeries]) -> Dict[str, Any]:
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


def write_chart_csv(path: str, export_payload: Dict[str, Any]) -> bool:
    rows = export_payload.get("rows", [])
    headers = [export_payload["x_label"]] + [series["name"] for series in export_payload.get("series", [])]
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        for row in rows:
            writer.writerow([row.get(header, "") for header in headers])
    return True


__all__ = [
    "build_chart_data_rows",
    "build_chart_export_payload",
    "serialize_chart_series",
    "serialize_chart_series_for_web",
    "write_chart_csv",
]
