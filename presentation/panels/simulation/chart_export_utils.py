import csv
from typing import Any, Dict, List, Sequence

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
    "write_chart_csv",
]
