from math import floor, log10
from typing import Iterable, Optional, Sequence, Tuple

import numpy as np
import pyqtgraph as pg


RangeTuple = Tuple[float, float]


def to_axis_values(values: Sequence[float], *, log_enabled: bool) -> np.ndarray:
    """Map physical values to the coordinates used by a Qt view box."""

    array = np.asarray(values, dtype=float)
    if not log_enabled:
        return array
    transformed = np.full(array.shape, np.nan, dtype=float)
    valid = np.isfinite(array) & (array > 0)
    transformed[valid] = np.log10(array[valid])
    return transformed


def sample_series_at_x(
    x_values: Sequence[float],
    y_values: Sequence[float],
    x_position: float,
    *,
    log_x: bool = False,
) -> Optional[float]:
    """Sample a finite series without applying interpolation to invalid X.

    NumPy requires interpolation coordinates to be monotonically increasing.
    Simulator time/frequency vectors normally satisfy that contract; descending
    sweeps are reversed.  For duplicate or genuinely non-monotonic coordinates
    (for example a nested DC sweep), sampling is rejected because one X value
    identifies multiple outer-sweep branches.
    """

    try:
        x_array = np.asarray(x_values, dtype=float)
        y_array = np.asarray(y_values, dtype=float)
        position = float(x_position)
    except (TypeError, ValueError, OverflowError):
        return None
    if x_array.ndim != 1 or y_array.ndim != 1 or not np.isfinite(position):
        return None
    pair_count = min(len(x_array), len(y_array))
    if pair_count <= 0:
        return None
    x_array = x_array[:pair_count]
    y_array = y_array[:pair_count]
    valid = np.isfinite(x_array) & np.isfinite(y_array)
    if log_x:
        valid &= x_array > 0
        x_array = to_axis_values(x_array, log_enabled=True)
    original_indexes = np.flatnonzero(valid)
    x_array = x_array[valid]
    y_array = y_array[valid]
    if len(x_array) == 0:
        return None
    if len(x_array) == 1:
        return float(y_array[0]) if position == x_array[0] else None

    lower_bound = float(np.min(x_array))
    upper_bound = float(np.max(x_array))
    if position < lower_bound or position > upper_bound:
        return None

    differences = np.diff(x_array)
    if np.all(differences > 0):
        return _interpolate_contiguous(x_array, y_array, original_indexes, position)
    if np.all(differences < 0):
        return _interpolate_contiguous(
            x_array[::-1],
            y_array[::-1],
            original_indexes[::-1],
            position,
        )
    return None


def has_unambiguous_x_axis(
    x_values: Sequence[float],
    *,
    log_x: bool = False,
) -> bool:
    """Return whether a scalar X cursor identifies at most one sweep branch."""

    try:
        x_array = np.asarray(x_values, dtype=float)
    except (TypeError, ValueError, OverflowError):
        return False
    if x_array.ndim != 1:
        return False
    finite = np.isfinite(x_array)
    if log_x:
        finite &= x_array > 0
    x_array = x_array[finite]
    if len(x_array) <= 1:
        return bool(len(x_array))
    differences = np.diff(x_array)
    return bool(np.all(differences > 0) or np.all(differences < 0))


def _interpolate_contiguous(
    x_values: np.ndarray,
    y_values: np.ndarray,
    original_indexes: np.ndarray,
    position: float,
) -> Optional[float]:
    """Interpolate only within one uninterrupted finite sample segment."""

    exact = np.flatnonzero(x_values == position)
    if exact.size:
        return float(y_values[int(exact[0])])
    right = int(np.searchsorted(x_values, position, side="right"))
    if right <= 0 or right >= len(x_values):
        return None
    left = right - 1
    if abs(int(original_indexes[right]) - int(original_indexes[left])) != 1:
        return None
    x_left = float(x_values[left])
    x_right = float(x_values[right])
    fraction = (position - x_left) / (x_right - x_left)
    return float(y_values[left] + fraction * (y_values[right] - y_values[left]))


def optimize_plot_data_item(item: pg.PlotDataItem, x_values: Sequence[float]) -> None:
    """Enable pyqtgraph's peak-preserving large-series render path."""

    x_array = np.asarray(x_values, dtype=float)
    item.setDownsampling(auto=True, method="peak")
    item.setClipToView(
        bool(
            x_array.ndim == 1
            and len(x_array) > 1
            and np.all(np.isfinite(x_array))
            and np.all(np.diff(x_array) > 0)
        )
    )


def unwrap_phase_degrees(values: Sequence[float]) -> np.ndarray:
    """Unwrap each contiguous finite phase segment independently."""

    try:
        phase = np.asarray(values, dtype=float)
    except (TypeError, ValueError, OverflowError):
        return np.empty(0, dtype=float)
    if phase.ndim != 1:
        return np.empty(0, dtype=float)
    result = np.full(phase.shape, np.nan, dtype=float)
    finite = np.isfinite(phase)
    padded = np.concatenate(([False], finite, [False]))
    transitions = np.diff(padded.astype(np.int8))
    for start, stop in zip(
        np.flatnonzero(transitions == 1),
        np.flatnonzero(transitions == -1),
    ):
        result[start:stop] = np.degrees(
            np.unwrap(np.radians(phase[start:stop]))
        )
    return result


def sample_phase_degrees_at_x(
    x_values: Sequence[float],
    phase_degrees: Sequence[float],
    x_position: float,
    *,
    log_x: bool = False,
) -> Optional[float]:
    """Interpolate phase on the same continuous representation as the plot."""

    try:
        x_array = np.asarray(x_values, dtype=float)
        phase_array = np.asarray(phase_degrees, dtype=float)
    except (TypeError, ValueError, OverflowError):
        return None
    if x_array.ndim != 1 or phase_array.ndim != 1:
        return None
    pair_count = min(len(x_array), len(phase_array))
    if pair_count <= 0:
        return None
    sampled = sample_series_at_x(
        x_array[:pair_count],
        unwrap_phase_degrees(phase_array[:pair_count]),
        x_position,
        log_x=log_x,
    )
    return sampled


def normalize_range(range_tuple: Optional[Sequence[float]]) -> Optional[RangeTuple]:
    if range_tuple is None or len(range_tuple) != 2:
        return None

    start = float(range_tuple[0])
    end = float(range_tuple[1])
    if not np.isfinite(start) or not np.isfinite(end):
        return None
    if start <= end:
        return start, end
    return end, start


def clamp_range(
    requested_range: Optional[Sequence[float]],
    allowed_range: Optional[Sequence[float]],
    *,
    positive_only: bool = False,
) -> Optional[RangeTuple]:
    normalized_requested = normalize_range(requested_range)
    normalized_allowed = normalize_range(allowed_range)
    if normalized_requested is None or normalized_allowed is None:
        return None

    requested_min, requested_max = normalized_requested
    allowed_min, allowed_max = normalized_allowed
    clamped_min = max(requested_min, allowed_min)
    clamped_max = min(requested_max, allowed_max)

    if positive_only:
        clamped_min = max(clamped_min, 1e-30)
        clamped_max = max(clamped_max, clamped_min)

    if clamped_max < clamped_min:
        return None
    return clamped_min, clamped_max


def _as_finite_array(values: Sequence[float], *, positive_only: bool = False) -> np.ndarray:
    array = np.asarray(values, dtype=float)
    if array.size == 0:
        return array
    mask = np.isfinite(array)
    if positive_only:
        mask &= array > 0
    return array[mask]


def finite_range(values: Sequence[float], *, positive_only: bool = False) -> Optional[RangeTuple]:
    array = _as_finite_array(values, positive_only=positive_only)
    if array.size == 0:
        return None
    return float(np.min(array)), float(np.max(array))


def merge_ranges(ranges: Iterable[Optional[RangeTuple]]) -> Optional[RangeTuple]:
    collected = [item for item in ranges if item is not None]
    if not collected:
        return None
    return (
        min(item[0] for item in collected),
        max(item[1] for item in collected),
    )


def nice_tick_spacing(span: float, *, target_ticks: int = 14) -> float:
    if not np.isfinite(span) or span <= 0:
        return 1.0

    rough_step = span / max(target_ticks, 1)
    magnitude = 10 ** floor(log10(rough_step))
    normalized = rough_step / magnitude

    if normalized <= 1:
        step = 1 * magnitude
    elif normalized <= 2:
        step = 2 * magnitude
    elif normalized <= 2.5:
        step = 2.5 * magnitude
    elif normalized <= 5:
        step = 5 * magnitude
    else:
        step = 10 * magnitude
    return float(step)


def apply_dynamic_tick_spacing(
    axis: pg.AxisItem,
    range_tuple: Optional[RangeTuple],
    *,
    log_enabled: bool,
    target_ticks: int = 14,
) -> None:
    if log_enabled or range_tuple is None:
        axis.setTickSpacing()
        return

    minimum, maximum = range_tuple
    span = maximum - minimum
    if not np.isfinite(span) or span <= 0:
        axis.setTickSpacing()
        return

    major = nice_tick_spacing(span, target_ticks=target_ticks)
    minor = major / 5.0 if major > 0 else None
    axis.setTickSpacing(major=major, minor=minor)


__all__ = [
    "RangeTuple",
    "apply_dynamic_tick_spacing",
    "clamp_range",
    "finite_range",
    "has_unambiguous_x_axis",
    "merge_ranges",
    "nice_tick_spacing",
    "normalize_range",
    "optimize_plot_data_item",
    "sample_phase_degrees_at_x",
    "sample_series_at_x",
    "to_axis_values",
    "unwrap_phase_degrees",
]
