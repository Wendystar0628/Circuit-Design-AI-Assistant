"""Small, explicit statistics helper for in-memory simulation series.

The helper reports descriptive sample statistics only.  It intentionally does
not call a discrete sign-change count a circuit "zero-crossing" measurement,
and it labels the arithmetic mean ``sample_mean`` because non-uniform sweeps
require integration and interpolation for a physical time/frequency average.
"""

from __future__ import annotations

import enum
import math
from dataclasses import dataclass
from typing import Mapping, Optional, Sequence, Tuple


class AnchorScale(str, enum.Enum):
    LINEAR = "linear"
    LOG = "log"


@dataclass(frozen=True)
class SeriesStats:
    name: str
    samples: int
    min_value: float
    max_value: float
    sample_mean: float
    initial_value: float
    final_value: float
    peak_to_peak: float


@dataclass(frozen=True)
class AnchorRow:
    x: float
    values: Tuple[Optional[float], ...]


@dataclass(frozen=True)
class SeriesReadResult:
    x_column_name: str
    signal_column_names: Tuple[str, ...]
    total_rows: int
    x_range: Tuple[float, float]
    x_order: str
    stats: Tuple[SeriesStats, ...]
    anchors: Tuple[AnchorRow, ...]
    anchor_scale_requested: AnchorScale
    anchor_scale_effective: AnchorScale


def read_series_table(
    *,
    x_column_name: str,
    signal_column_names: Sequence[str],
    x_values: Sequence[object],
    signal_columns: Mapping[str, Sequence[object]],
    anchor_count: int = 14,
    anchor_scale: AnchorScale = AnchorScale.LINEAR,
) -> SeriesReadResult:
    """Summarise one aligned simulation table.

    The x column must be finite and every named signal column must have the
    same row count.  Signal cells may be missing/non-finite; they appear as
    ``None`` in anchors and do not contribute to descriptive statistics.
    """
    if isinstance(anchor_count, bool):
        raise ValueError("anchor_count must be an integer")
    anchor_count = max(4, min(32, int(anchor_count)))

    names = tuple(str(name).strip() for name in signal_column_names)
    if any(not name for name in names):
        raise ValueError("signal names must be non-empty")
    if len(set(names)) != len(names):
        raise ValueError("signal names must be unique")

    parsed_x = tuple(_required_finite(value, "x axis") for value in x_values)
    row_count = len(parsed_x)
    parsed_columns = {}
    for name in names:
        if name not in signal_columns:
            raise ValueError(f"missing signal column {name!r}")
        raw_column = signal_columns[name]
        if len(raw_column) != row_count:
            raise ValueError(
                f"signal column {name!r} has {len(raw_column)} rows; "
                f"expected {row_count}"
            )
        parsed_columns[name] = tuple(_optional_finite(value) for value in raw_column)

    if row_count == 0:
        nan = float("nan")
        return SeriesReadResult(
            x_column_name=str(x_column_name or "X"),
            signal_column_names=names,
            total_rows=0,
            x_range=(nan, nan),
            x_order="empty",
            stats=tuple(_empty_stats(name) for name in names),
            anchors=(),
            anchor_scale_requested=anchor_scale,
            anchor_scale_effective=anchor_scale,
        )

    effective_scale = anchor_scale
    if (
        anchor_scale is AnchorScale.LOG
        and (min(parsed_x) <= 0 or min(parsed_x) == max(parsed_x))
    ):
        effective_scale = AnchorScale.LINEAR

    if effective_scale is AnchorScale.LOG:
        anchor_indices = _log_anchor_indices(parsed_x, anchor_count)
    else:
        anchor_indices = _linear_anchor_indices(row_count, anchor_count)

    anchors = tuple(
        AnchorRow(
            x=parsed_x[index],
            values=tuple(parsed_columns[name][index] for name in names),
        )
        for index in anchor_indices
    )
    return SeriesReadResult(
        x_column_name=str(x_column_name or "X"),
        signal_column_names=names,
        total_rows=row_count,
        x_range=(min(parsed_x), max(parsed_x)),
        x_order=_x_order(parsed_x),
        stats=tuple(_stats(name, parsed_columns[name]) for name in names),
        anchors=anchors,
        anchor_scale_requested=anchor_scale,
        anchor_scale_effective=effective_scale,
    )


def _stats(name: str, values: Sequence[Optional[float]]) -> SeriesStats:
    finite = [value for value in values if value is not None]
    if not finite:
        return _empty_stats(name)
    minimum = min(finite)
    maximum = max(finite)
    return SeriesStats(
        name=name,
        samples=len(finite),
        min_value=minimum,
        max_value=maximum,
        sample_mean=math.fsum(finite) / len(finite),
        initial_value=finite[0],
        final_value=finite[-1],
        peak_to_peak=maximum - minimum,
    )


def _empty_stats(name: str) -> SeriesStats:
    nan = float("nan")
    return SeriesStats(
        name=name,
        samples=0,
        min_value=nan,
        max_value=nan,
        sample_mean=nan,
        initial_value=nan,
        final_value=nan,
        peak_to_peak=nan,
    )


def _linear_anchor_indices(total_rows: int, count: int) -> Tuple[int, ...]:
    if total_rows <= count:
        return tuple(range(total_rows))
    step = (total_rows - 1) / (count - 1)
    return tuple(sorted({round(index * step) for index in range(count)}))


def _log_anchor_indices(
    x_values: Sequence[float],
    count: int,
) -> Tuple[int, ...]:
    log_min = math.log10(min(x_values))
    log_max = math.log10(max(x_values))
    targets = [
        log_min + index * (log_max - log_min) / (count - 1)
        for index in range(count)
    ]
    chosen = {
        min(
            range(len(x_values)),
            key=lambda row: abs(math.log10(x_values[row]) - target),
        )
        for target in targets
    }
    return tuple(sorted(chosen))


def _x_order(values: Sequence[float]) -> str:
    if len(values) < 2:
        return "constant"
    deltas = [right - left for left, right in zip(values, values[1:])]
    if all(delta > 0 for delta in deltas):
        return "increasing"
    if all(delta < 0 for delta in deltas):
        return "decreasing"
    if all(delta == 0 for delta in deltas):
        return "constant"
    return "non_monotonic"


def _required_finite(value: object, label: str) -> float:
    parsed = _optional_finite(value)
    if parsed is None:
        raise ValueError(f"{label} contains a missing or non-finite value")
    return parsed


def _optional_finite(value: object) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


__all__ = [
    "AnchorScale",
    "SeriesStats",
    "AnchorRow",
    "SeriesReadResult",
    "read_series_table",
]
