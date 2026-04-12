from math import floor, log10
from typing import Iterable, Optional, Sequence, Tuple

import numpy as np
import pyqtgraph as pg


RangeTuple = Tuple[float, float]


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
