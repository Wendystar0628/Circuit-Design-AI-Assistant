"""Pure ``DisplayMetric`` factory.

Converts ``SimulationResult.measurements`` into a list of
``DisplayMetric`` rows, merging in user-authored target strings. The
factory is deliberately **stateless** and **UI-free** so that both the
simulation panel (via the view-model) and the headless artifact
persistence service can produce identical metric tables from the same
inputs.

Inputs:

- ``result``: a fully-populated ``SimulationResult``. Only
  ``measurements`` and ``file_path`` are consulted.
- ``targets``: ``{metric_name: target_text}``. Typically sourced from
  ``MetricTargetService.get_targets_for_file(...)`` on the UI side; on
  the agent side callers pass ``{}`` (targets are project-local and
  outside the agent job's concern).

Formatting rules mirror the historical ViewModel logic so the on-disk
``metrics.csv`` / ``metrics.json`` reads exactly like what the user
sees in the panel.
"""

from __future__ import annotations

import re
from typing import Dict, List, Mapping, Optional

from domain.simulation.measure.measure_metadata import measure_metadata_resolver
from domain.simulation.measure.measure_result import MeasureResult, MeasureStatus
from domain.simulation.models.display_metric import DisplayMetric
from domain.simulation.models.simulation_result import SimulationResult


_NUMERIC_PREFIX = re.compile(r"^([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)\s*(.*)$")


class DisplayMetricBuilder:
    def build(
        self,
        result: Optional[SimulationResult],
        targets: Optional[Mapping[str, str]] = None,
    ) -> List[DisplayMetric]:
        if result is None or not getattr(result, "success", False):
            return []
        measurements = getattr(result, "measurements", None) or []
        resolved_targets: Dict[str, str] = dict(targets or {})

        rows: List[DisplayMetric] = []
        for measure in measurements:
            if not isinstance(measure, MeasureResult):
                continue
            if measure.status != MeasureStatus.OK or measure.value is None:
                continue
            metadata = measure_metadata_resolver.resolve(
                measure.name,
                statement=measure.statement,
                description=measure.description,
                fallback_unit=measure.unit,
            )
            display_name = measure.display_name or metadata.display_name
            rows.append(
                self._make_row(
                    name=measure.name,
                    value=measure.value,
                    unit=metadata.unit,
                    display_name=display_name,
                    target=resolved_targets.get(measure.name, ""),
                )
            )
        return rows

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _make_row(
        self,
        *,
        name: str,
        value: object,
        unit: str,
        display_name: str,
        target: str,
    ) -> DisplayMetric:
        raw_value: Optional[float] = None
        formatted_value: str = str(value) if value is not None else "N/A"

        if isinstance(value, (int, float)):
            raw_value = float(value)
            formatted_value = self._format_with_unit(raw_value, unit)
        elif isinstance(value, str):
            match = _NUMERIC_PREFIX.match(value.strip())
            if match:
                try:
                    raw_value = float(match.group(1))
                    unit = match.group(2) or unit
                    formatted_value = value
                except ValueError:
                    pass

        return DisplayMetric(
            name=name,
            display_name=display_name,
            value=formatted_value,
            unit=unit,
            raw_value=raw_value,
            target=target,
        )

    def _format_with_unit(self, value: float, unit: str) -> str:
        abs_value = abs(value)
        if abs_value == 0:
            formatted = "0"
        elif abs_value >= 1e9:
            formatted = f"{value / 1e9:.2f}G"
        elif abs_value >= 1e6:
            formatted = f"{value / 1e6:.2f}M"
        elif abs_value >= 1e3:
            formatted = f"{value / 1e3:.2f}k"
        elif abs_value >= 1:
            formatted = f"{value:.2f}"
        elif abs_value >= 1e-3:
            formatted = f"{value * 1e3:.2f}m"
        elif abs_value >= 1e-6:
            formatted = f"{value * 1e6:.2f}\u03bc"
        elif abs_value >= 1e-9:
            formatted = f"{value * 1e9:.2f}n"
        else:
            formatted = f"{value:.2e}"
        return f"{formatted} {unit}" if unit else formatted


display_metric_builder = DisplayMetricBuilder()


__all__ = ["DisplayMetricBuilder", "display_metric_builder"]
