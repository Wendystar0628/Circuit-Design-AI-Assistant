from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


@dataclass(frozen=True)
class MeasurementPointValue:
    label: str
    value_text: str


@dataclass(frozen=True)
class MeasurementPointSample:
    title: str
    plot_series_name: str
    plot_axis_key: str
    plot_y_value: float
    values: List[MeasurementPointValue]


def normalize_bounds(bounds: Optional[Tuple[float, float]]) -> Optional[Tuple[float, float]]:
    if bounds is None:
        return None
    minimum = float(bounds[0])
    maximum = float(bounds[1])
    if minimum <= maximum:
        return minimum, maximum
    return maximum, minimum


def midpoint_of_bounds(bounds: Optional[Tuple[float, float]]) -> Optional[float]:
    normalized = normalize_bounds(bounds)
    if normalized is None:
        return None
    return (normalized[0] + normalized[1]) / 2.0


def clamp_to_bounds(value: Optional[float], bounds: Optional[Tuple[float, float]]) -> Optional[float]:
    if value is None:
        return None
    normalized = normalize_bounds(bounds)
    if normalized is None:
        return float(value)
    return min(max(float(value), normalized[0]), normalized[1])


def serialize_measurement_point_sample(sample: MeasurementPointSample) -> Dict[str, Any]:
    return {
        "title": sample.title,
        "plot_series_name": sample.plot_series_name,
        "plot_axis_key": sample.plot_axis_key,
        "plot_y": float(sample.plot_y_value),
        "values": [
            {
                "label": value.label,
                "value_text": value.value_text,
            }
            for value in sample.values
        ],
    }


__all__ = [
    "MeasurementPointSample",
    "MeasurementPointValue",
    "clamp_to_bounds",
    "midpoint_of_bounds",
    "normalize_bounds",
    "serialize_measurement_point_sample",
]
