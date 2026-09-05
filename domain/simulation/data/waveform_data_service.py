"""Authoritative waveform access and viewport decimation.

The service deliberately has no cache or resolution pyramid.  A viewport is
first cut from the finite raw simulator samples and is then decimated once.
This makes zoom detail independent from an earlier whole-trace preview and
keeps the implementation stateless.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

from domain.simulation.data.downsampler import (
    align_xy,
    crop_to_viewport,
    downsample_preserving_gaps,
)
from domain.simulation.data.signal_semantics import (
    VIRTUAL_COMPLEX_COMPONENT_SUFFIXES,
    insert_nested_dc_breaks,
    nested_dc_secondary_values,
    normalize_simulation_signal_name,
    parse_nested_dc_sweep,
    resolve_signal_type,
    split_virtual_complex_component_name,
)
from domain.simulation.data.trace_analysis_service import project_trace_values
from domain.simulation.models.simulation_result import SimulationData, SimulationResult


@dataclass
class WaveformData:
    signal_name: str
    x_data: np.ndarray
    y_data: np.ndarray
    point_count: int = field(init=False)
    x_range: Tuple[float, float] = field(init=False)
    y_range: Tuple[float, float] = field(init=False)
    is_downsampled: bool = False
    original_points: int = 0

    def __post_init__(self) -> None:
        self.x_data, self.y_data = align_xy(self.x_data, self.y_data)
        invalid_x = ~np.isfinite(self.x_data)
        self.x_data[invalid_x] = np.nan
        self.y_data[invalid_x] = np.nan
        self.point_count = len(self.x_data)
        finite_pairs = np.isfinite(self.x_data) & np.isfinite(self.y_data)
        self.x_range = _finite_bounds(self.x_data[finite_pairs])
        self.y_range = _finite_bounds(self.y_data[finite_pairs])
        if self.original_points <= 0:
            self.original_points = self.point_count


@dataclass
class TableSnapshot:
    result_path: str
    analysis_type: str
    version: int
    session_id: str
    timestamp: str
    x_label: str
    signal_names: List[str]
    x_values: np.ndarray
    signal_columns: Dict[str, np.ndarray]

    @property
    def total_rows(self) -> int:
        return int(len(self.x_values))


_VIRTUAL_COMPONENT_PRIORITY = {
    suffix: index
    for index, suffix in enumerate(VIRTUAL_COMPLEX_COMPONENT_SUFFIXES)
}


class WaveformDataService:
    """Stateless access to validated simulator vectors."""

    def get_initial_data(
        self,
        result: SimulationResult,
        signal_name: str,
        target_points: int = 500,
    ) -> Optional[WaveformData]:
        if target_points < 2:
            return None
        prepared = self._prepare_result_series(result, signal_name)
        if prepared is None:
            return None
        resolved_name, x_data, y_data = prepared
        original_points = len(x_data)
        x_out, y_out = downsample_preserving_gaps(x_data, y_data, target_points)
        if len(x_out) == 0:
            return None
        return WaveformData(
            signal_name=resolved_name,
            x_data=x_out,
            y_data=y_out,
            is_downsampled=len(x_out) < original_points,
            original_points=original_points,
        )

    def get_viewport_data(
        self,
        result: SimulationResult,
        signal_name: str,
        x_min: float,
        x_max: float,
        target_points: int = 1000,
    ) -> Optional[WaveformData]:
        if target_points < 2 or not np.isfinite(x_min) or not np.isfinite(x_max):
            return None
        prepared = self._prepare_result_series(result, signal_name)
        if prepared is None:
            return None
        resolved_name, x_data, y_data = prepared
        original_points = len(x_data)
        lower, upper = sorted((float(x_min), float(x_max)))

        viewport_x, viewport_y = crop_to_viewport(x_data, y_data, lower, upper)
        if len(viewport_x) == 0:
            return None
        x_out, y_out = downsample_preserving_gaps(viewport_x, viewport_y, target_points)
        if len(x_out) == 0:
            return None
        return WaveformData(
            signal_name=resolved_name,
            x_data=x_out,
            y_data=y_out,
            is_downsampled=len(x_out) < len(viewport_x),
            original_points=original_points,
        )

    def get_signal_range(
        self,
        result: SimulationResult,
        signal_name: str,
    ) -> Optional[Tuple[float, float]]:
        prepared = self._prepare_result_series(result, signal_name)
        if prepared is None:
            return None
        _, x_values, values = prepared
        finite_pairs = np.isfinite(x_values) & np.isfinite(values)
        values = values[finite_pairs]
        finite_values = values[np.isfinite(values)]
        if finite_values.size == 0:
            return None
        return float(np.min(finite_values)), float(np.max(finite_values))

    def get_signal_data(
        self,
        result: SimulationResult,
        signal_name: str,
    ) -> Optional[np.ndarray]:
        if result is None or not result.success or result.data is None:
            return None
        resolved_signal_name = self.resolve_signal_name(result, signal_name)
        if resolved_signal_name is None:
            return None
        signal_data = self._get_signal_data(result.data, resolved_signal_name)
        return np.asarray(signal_data) if signal_data is not None else None

    def get_resolved_signal_names(
        self,
        result: SimulationResult,
        signal_names: Optional[List[str]] = None,
    ) -> List[str]:
        if result is None or not result.success or result.data is None:
            return []

        data = result.data
        requested_signals = signal_names if signal_names is not None else data.get_signal_names()
        resolved: List[str] = []
        seen = set()
        for signal_name in requested_signals:
            for resolved_name in self._expand_signal_name(data, signal_name):
                if resolved_name not in seen:
                    resolved.append(resolved_name)
                    seen.add(resolved_name)
        return sorted(resolved, key=lambda name: self._get_signal_sort_key(data, name))

    def resolve_signal_name(
        self,
        result: SimulationResult,
        signal_name: str,
    ) -> Optional[str]:
        if result is None or not result.success or result.data is None:
            return None
        resolved_names = self._expand_signal_name(result.data, signal_name)
        if not resolved_names:
            return None
        return min(resolved_names, key=lambda name: self._get_signal_sort_key(result.data, name))

    def get_classified_signals(self, result: SimulationResult) -> Dict[str, List[str]]:
        classified: Dict[str, List[str]] = {
            "voltage": [],
            "current": [],
            "other": [],
        }
        if result is None or not result.success or result.data is None:
            return classified
        signal_types = getattr(result.data, "signal_types", {})
        for name in self.get_resolved_signal_names(result):
            classified[self.get_signal_type(name, signal_types)].append(name)
        return classified

    @staticmethod
    def get_signal_type(
        name: str,
        signal_types: Optional[Dict[str, str]] = None,
    ) -> str:
        return resolve_signal_type(name, signal_types)

    @staticmethod
    def is_voltage_signal(name: str, signal_types: Optional[Dict[str, str]] = None) -> bool:
        return WaveformDataService.get_signal_type(name, signal_types) == "voltage"

    @staticmethod
    def is_current_signal(name: str, signal_types: Optional[Dict[str, str]] = None) -> bool:
        return WaveformDataService.get_signal_type(name, signal_types) == "current"

    def build_table_snapshot(
        self,
        result: SimulationResult,
        signal_names: Optional[List[str]] = None,
    ) -> Optional[TableSnapshot]:
        if result is None or not result.success or result.data is None:
            return None
        x_data, x_label = self._get_table_x_axis(result)
        if x_data is None:
            return None

        try:
            raw_x_values = np.asarray(x_data, dtype=float)
        except (TypeError, ValueError, OverflowError):
            return None
        if raw_x_values.ndim != 1 or not np.all(np.isfinite(raw_x_values)):
            return None
        x_values = raw_x_values.copy()

        resolved_signal_names = self.get_resolved_signal_names(result, signal_names)
        signal_columns: Dict[str, np.ndarray] = {}
        total_rows = len(x_values)
        nested_sweep = parse_nested_dc_sweep(result.analysis_type, result.analysis_command)
        if nested_sweep is not None:
            secondary_values = nested_dc_secondary_values(raw_x_values, nested_sweep)
            if np.any(np.isfinite(secondary_values)):
                secondary_name = nested_sweep.secondary_column_label
                signal_columns[secondary_name] = secondary_values.copy()
                resolved_signal_names = [secondary_name, *resolved_signal_names]
        for signal_name in resolved_signal_names:
            if signal_name in signal_columns:
                continue
            signal_data = self._get_signal_data(result.data, signal_name)
            column = np.full(total_rows, np.nan, dtype=float)
            if signal_data is not None:
                for row in range(total_rows):
                    if row >= len(signal_data):
                        continue
                    scalar_value = self._to_table_scalar_value(signal_data[row])
                    if scalar_value is not None and np.isfinite(scalar_value):
                        column[row] = scalar_value
            signal_columns[signal_name] = column

        # Tables are native rows, not rendered polylines. The outer-source
        # column identifies nested DC branches without inventing NaN rows.
        return TableSnapshot(
            result_path=result.file_path,
            analysis_type=result.analysis_type,
            version=result.version,
            session_id=result.session_id,
            timestamp=result.timestamp,
            x_label=x_label,
            signal_names=resolved_signal_names,
            x_values=x_values,
            signal_columns=signal_columns,
        )

    def _prepare_result_series(
        self,
        result: SimulationResult,
        signal_name: str,
    ) -> Optional[Tuple[str, np.ndarray, np.ndarray]]:
        if result is None or not result.success or result.data is None:
            return None
        resolved_signal_name = self.resolve_signal_name(result, signal_name)
        if resolved_signal_name is None:
            return None
        x_data = result.get_x_axis_data()
        y_data = self._get_signal_data(result.data, resolved_signal_name)
        if x_data is None or y_data is None:
            return None
        x_array, y_array = align_xy(x_data, y_data)
        nested_sweep = parse_nested_dc_sweep(result.analysis_type, result.analysis_command)
        if nested_sweep is not None:
            x_array, y_array = insert_nested_dc_breaks(x_array, y_array, nested_sweep)
        if len(x_array) == 0 or not np.any(np.isfinite(x_array) & np.isfinite(y_array)):
            return None
        return resolved_signal_name, x_array, y_array

    def _expand_signal_name(self, data: SimulationData, signal_name: str) -> List[str]:
        available_signals = set(data.get_signal_names())
        base_name, component_suffix = split_virtual_complex_component_name(signal_name)
        candidate_bases = [base_name]
        normalized_base = normalize_simulation_signal_name(base_name)
        if normalized_base not in candidate_bases:
            candidate_bases.append(normalized_base)

        if component_suffix:
            for candidate_base in candidate_bases:
                base_signal = data.get_signal(candidate_base)
                if base_signal is not None and np.iscomplexobj(base_signal):
                    return [f"{candidate_base}{component_suffix}"]
            return []

        for candidate_name in candidate_bases:
            if candidate_name not in available_signals:
                continue
            signal_data = data.get_signal(candidate_name)
            if signal_data is None:
                continue
            if np.iscomplexobj(signal_data):
                return [
                    f"{candidate_name}{suffix}"
                    for suffix in VIRTUAL_COMPLEX_COMPONENT_SUFFIXES
                ]
            return [candidate_name]
        return []

    def _get_signal_sort_key(
        self,
        data: SimulationData,
        signal_name: str,
    ) -> Tuple[int, int, str, int, str]:
        signal_types = getattr(data, "signal_types", {})
        base_name, component_suffix = split_virtual_complex_component_name(signal_name)
        signal_type = self.get_signal_type(base_name, signal_types)
        type_rank = {"voltage": 0, "current": 1, "other": 2}.get(signal_type, 2)
        name_lower = base_name.lower()
        role_rank = 0 if "out" in name_lower else 1 if "in" in name_lower else 2
        component_rank = _VIRTUAL_COMPONENT_PRIORITY.get(
            component_suffix,
            len(_VIRTUAL_COMPONENT_PRIORITY),
        )
        return role_rank, type_rank, name_lower, component_rank, signal_name.lower()

    def _get_signal_data(
        self,
        data: SimulationData,
        signal_name: str,
    ) -> Optional[np.ndarray]:
        base_name, component_suffix = split_virtual_complex_component_name(signal_name)
        if not component_suffix:
            signal_data = data.get_signal(signal_name)
            return np.asarray(signal_data) if signal_data is not None else None
        base_signal = data.get_signal(base_name)
        if base_signal is None or not np.iscomplexobj(base_signal):
            return None
        component = {"_mag": "magnitude", "_phase": "phase", "_real": "real", "_imag": "imaginary"}.get(component_suffix)
        return project_trace_values(np.asarray(base_signal), component) if component else None

    @staticmethod
    def _to_table_scalar_value(value: object) -> Optional[float]:
        if value is None:
            return None
        if np.iscomplexobj(value):
            complex_value = complex(value)
            if abs(complex_value.imag) > 1e-15:
                return None
            return float(complex_value.real)
        try:
            return float(value)
        except (TypeError, ValueError, OverflowError):
            return None

    @staticmethod
    def _get_table_x_axis(result: SimulationResult) -> Tuple[Optional[np.ndarray], str]:
        x_axis_data = result.get_x_axis_data()
        if x_axis_data is not None:
            return x_axis_data, result.get_x_axis_label()
        data = result.data
        if data is None:
            return None, "X"
        row_count = max(
            (len(signal) for signal in data.signals.values() if signal is not None),
            default=0,
        )
        if row_count:
            return np.arange(row_count, dtype=float), "Index"
        return None, "X"


def _finite_bounds(values: np.ndarray) -> Tuple[float, float]:
    finite_values = np.asarray(values, dtype=float)
    finite_values = finite_values[np.isfinite(finite_values)]
    if finite_values.size == 0:
        return 0.0, 0.0
    return float(np.min(finite_values)), float(np.max(finite_values))


waveform_data_service = WaveformDataService()


__all__ = [
    "WaveformData",
    "TableSnapshot",
    "WaveformDataService",
    "waveform_data_service",
]
