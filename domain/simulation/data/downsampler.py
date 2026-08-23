"""Peak-preserving waveform decimation.

The UI needs an upper bound on rendered points without hiding short spikes.
Uniform index sampling and a global multi-resolution pyramid both lose that
guarantee for zoomed viewports.  This module performs one min/max-envelope pass
on the data that is actually going to be displayed.

Non-finite coordinate/value pairs delimit discontinuities.  They are excluded
from numeric domains and interpolation, but one explicit ``NaN`` separator is
retained between finite runs so a renderer cannot reconnect unrelated data.
"""

from __future__ import annotations

from typing import List, Tuple

import numpy as np


def align_xy(x: np.ndarray, y: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """Return trimmed one-dimensional float arrays without erasing gaps."""

    if x is None or y is None:
        return np.empty(0, dtype=np.float64), np.empty(0, dtype=np.float64)
    try:
        x_array = np.asarray(x, dtype=np.float64)
        y_array = np.asarray(y, dtype=np.float64)
    except (TypeError, ValueError, OverflowError):
        return np.empty(0, dtype=np.float64), np.empty(0, dtype=np.float64)
    if x_array.ndim != 1 or y_array.ndim != 1:
        return np.empty(0, dtype=np.float64), np.empty(0, dtype=np.float64)
    pair_count = min(len(x_array), len(y_array))
    if pair_count <= 0:
        return np.empty(0, dtype=np.float64), np.empty(0, dtype=np.float64)
    return x_array[:pair_count].copy(), y_array[:pair_count].copy()


def sanitize_xy(x: np.ndarray, y: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """Return aligned, one-dimensional, finite ``float64`` coordinate pairs.

    A truncated simulator vector is treated as a partial result: the unmatched
    tail is discarded instead of crashing the whole simulation surface.  A
    completely unusable vector returns two empty arrays.
    """

    x_array, y_array = align_xy(x, y)
    finite_mask = np.isfinite(x_array) & np.isfinite(y_array)
    return x_array[finite_mask].copy(), y_array[finite_mask].copy()


def crop_to_viewport(
    x: np.ndarray,
    y: np.ndarray,
    x_min: float,
    x_max: float,
) -> Tuple[np.ndarray, np.ndarray]:
    """Crop aligned raw samples to a viewport, retaining line neighbours."""

    x_array, y_array = align_xy(x, y)
    if len(x_array) == 0 or not np.isfinite(x_min) or not np.isfinite(x_max):
        return np.empty(0, dtype=np.float64), np.empty(0, dtype=np.float64)
    lower, upper = sorted((float(x_min), float(x_max)))
    indexes = viewport_indexes(x_array, lower, upper)
    if indexes.size == 0:
        return np.empty(0, dtype=np.float64), np.empty(0, dtype=np.float64)
    x_parts: List[np.ndarray] = []
    y_parts: List[np.ndarray] = []
    separator = np.array([np.nan], dtype=np.float64)
    starts = np.concatenate(([0], np.flatnonzero(np.diff(indexes) > 1) + 1))
    stops = np.concatenate((starts[1:], [len(indexes)]))
    for part_index, (start, stop) in enumerate(zip(starts, stops)):
        if part_index:
            x_parts.append(separator)
            y_parts.append(separator)
        selected = indexes[int(start) : int(stop)]
        x_parts.append(x_array[selected])
        y_parts.append(y_array[selected])
    return np.concatenate(x_parts), np.concatenate(y_parts)


def viewport_indexes(x_data: np.ndarray, lower: float, upper: float) -> np.ndarray:
    """Return every finite run's samples and segments touching an X interval."""

    x_array = np.asarray(x_data, dtype=float)
    if x_array.ndim != 1 or not np.isfinite(lower) or not np.isfinite(upper):
        return np.empty(0, dtype=np.int64)
    finite_mask = np.isfinite(x_array)
    if not np.any(finite_mask):
        return np.empty(0, dtype=np.int64)
    finite_x = x_array[finite_mask]
    if upper < float(np.min(finite_x)) or lower > float(np.max(finite_x)):
        return np.empty(0, dtype=np.int64)

    selected_parts: List[np.ndarray] = []
    for run_start, run_stop in _finite_runs(finite_mask):
        run_x = x_array[run_start:run_stop]
        if upper < float(np.min(run_x)) or lower > float(np.max(run_x)):
            continue

        local_candidates: List[np.ndarray] = []
        inside = np.flatnonzero((run_x >= lower) & (run_x <= upper))
        if inside.size:
            local_candidates.extend((inside - 1, inside, inside + 1))

        # Inspect every actual adjacent segment even when another run already
        # contains an in-viewport sample. Nested sweeps may use different point
        # grids, so one branch can cross a narrow viewport only between points.
        if len(run_x) >= 2:
            segment_min = np.minimum(run_x[:-1], run_x[1:])
            segment_max = np.maximum(run_x[:-1], run_x[1:])
            crossing_starts = np.flatnonzero(
                (segment_min <= upper) & (segment_max >= lower)
            )
            if crossing_starts.size:
                local_candidates.extend((crossing_starts, crossing_starts + 1))

        if not local_candidates:
            continue
        candidates = np.concatenate(local_candidates)
        candidates = candidates[(candidates >= 0) & (candidates < len(run_x))]
        if candidates.size:
            selected_parts.append(run_start + np.unique(candidates))

    if not selected_parts:
        return np.empty(0, dtype=np.int64)
    return np.unique(np.concatenate(selected_parts))


def downsample(
    x: np.ndarray,
    y: np.ndarray,
    target_points: int,
) -> Tuple[np.ndarray, np.ndarray]:
    """Decimate ``x``/``y`` to at most ``target_points`` while keeping peaks.

    The first and last finite samples are retained.  The interior is divided
    into contiguous buckets and both the minimum and maximum sample of each
    bucket are retained in their original order.  Consequently a one-sample
    excursion cannot disappear merely because it falls between uniform sample
    indexes.
    """

    if target_points < 2:
        raise ValueError(f"target_points must be >= 2, got {target_points}")

    x_array, y_array = sanitize_xy(x, y)
    point_count = len(x_array)
    if point_count <= target_points:
        return x_array, y_array
    if target_points == 2:
        indexes = np.array([0, point_count - 1], dtype=np.int64)
        return x_array[indexes], y_array[indexes]

    interior_slots = target_points - 2
    if interior_slots == 1:
        index = _largest_deviation_index(x_array, y_array)
        indexes = np.array([0, index, point_count - 1], dtype=np.int64)
        return x_array[indexes], y_array[indexes]

    bucket_count = max(1, interior_slots // 2)
    interior_indexes = np.arange(1, point_count - 1, dtype=np.int64)
    buckets = np.array_split(interior_indexes, bucket_count)
    selected = [0]
    for bucket in buckets:
        if bucket.size == 0:
            continue
        bucket_y = y_array[bucket]
        minimum_index = int(bucket[int(np.argmin(bucket_y))])
        maximum_index = int(bucket[int(np.argmax(bucket_y))])
        selected.extend(sorted({minimum_index, maximum_index}))
    selected.append(point_count - 1)

    # ``array_split`` plus two extrema per bucket is bounded by target_points.
    indexes = np.asarray(selected, dtype=np.int64)
    return x_array[indexes], y_array[indexes]


def downsample_preserving_gaps(
    x: np.ndarray,
    y: np.ndarray,
    target_points: int,
) -> Tuple[np.ndarray, np.ndarray]:
    """Peak-decimate finite runs while retaining explicit NaN separators.

    A non-finite X/Y pair is a discontinuity, not a sample that may simply be
    deleted.  Each contiguous finite run is decimated independently and runs
    are separated by one ``(nan, nan)`` marker.  The complete output, including
    separators, remains bounded by ``target_points``.
    """

    if target_points < 2:
        raise ValueError(f"target_points must be >= 2, got {target_points}")
    x_array, y_array = align_xy(x, y)
    if len(x_array) == 0:
        return x_array, y_array

    finite = np.isfinite(x_array) & np.isfinite(y_array)
    if not np.any(finite):
        return np.empty(0, dtype=np.float64), np.empty(0, dtype=np.float64)

    if len(x_array) <= target_points:
        x_out = x_array.copy()
        y_out = y_array.copy()
        invalid_x = ~np.isfinite(x_out)
        invalid_y = ~np.isfinite(y_out)
        x_out[invalid_x] = np.nan
        y_out[invalid_x | invalid_y] = np.nan
        return x_out, y_out

    runs = _finite_runs(finite)
    max_runs = max(1, (target_points + 1) // 2)
    if len(runs) > max_runs:
        selected = np.unique(np.linspace(0, len(runs) - 1, max_runs, dtype=np.int64))
        runs = [runs[int(index)] for index in selected]

    finite_budget = target_points - max(0, len(runs) - 1)
    targets = np.ones(len(runs), dtype=np.int64)
    remaining = finite_budget - len(runs)

    # Preserve both boundaries where the budget permits, then spend remaining
    # points on the run with the greatest current compression ratio.
    for index, (start, stop) in sorted(
        enumerate(runs),
        key=lambda item: item[1][1] - item[1][0],
        reverse=True,
    ):
        if remaining <= 0:
            break
        if stop - start > 1:
            targets[index] += 1
            remaining -= 1
    while remaining > 0:
        eligible = [
            index
            for index, (start, stop) in enumerate(runs)
            if targets[index] < stop - start
        ]
        if not eligible:
            break
        chosen = max(
            eligible,
            key=lambda index: (runs[index][1] - runs[index][0]) / targets[index],
        )
        targets[chosen] += 1
        remaining -= 1

    x_parts: List[np.ndarray] = []
    y_parts: List[np.ndarray] = []
    separator = np.array([np.nan], dtype=np.float64)
    for run_index, ((start, stop), run_target) in enumerate(zip(runs, targets)):
        run_x = x_array[start:stop]
        run_y = y_array[start:stop]
        if int(run_target) == 1:
            representative = int(np.argmax(np.abs(run_y)))
            sampled_x = run_x[representative : representative + 1]
            sampled_y = run_y[representative : representative + 1]
        else:
            sampled_x, sampled_y = downsample(run_x, run_y, int(run_target))
        if run_index:
            x_parts.append(separator)
            y_parts.append(separator)
        x_parts.append(sampled_x)
        y_parts.append(sampled_y)
    return np.concatenate(x_parts), np.concatenate(y_parts)


def _finite_runs(finite_mask: np.ndarray) -> List[Tuple[int, int]]:
    padded = np.concatenate(([False], finite_mask, [False]))
    transitions = np.diff(padded.astype(np.int8))
    starts = np.flatnonzero(transitions == 1)
    stops = np.flatnonzero(transitions == -1)
    return [(int(start), int(stop)) for start, stop in zip(starts, stops)]


def _largest_deviation_index(x: np.ndarray, y: np.ndarray) -> int:
    """Pick the interior sample furthest from the endpoint chord."""

    x0, x1 = float(x[0]), float(x[-1])
    y0, y1 = float(y[0]), float(y[-1])
    interior = np.arange(1, len(x) - 1, dtype=np.int64)
    if x1 == x0:
        deviations = np.abs(y[interior] - (y0 + y1) / 2.0)
    else:
        expected = y0 + (y1 - y0) * (x[interior] - x0) / (x1 - x0)
        deviations = np.abs(y[interior] - expected)
    return int(interior[int(np.argmax(deviations))])


__all__ = [
    "align_xy",
    "crop_to_viewport",
    "downsample",
    "downsample_preserving_gaps",
    "sanitize_xy",
    "viewport_indexes",
]
