"""Pure ``DisplayMetric`` factory.

Converts ``SimulationResult.measurements`` into a list of
``DisplayMetric`` rows, merging in user-authored target strings. The
factory is stateless and UI-free so the panel, root-backed agent reader and
manual exporter produce the same formatting from the same measurements.

Inputs:

- ``result``: a fully-populated ``SimulationResult``. Only
  ``measurements`` and ``file_path`` are consulted.
- ``targets``: ``{metric_name: target_text}``. Typically sourced from
  ``MetricTargetService.get_targets_for_file(...)`` on the UI side. Root-backed
  agent reads pass ``{}`` because mutable targets are not part of an immutable
  simulation result.

Formatting rules are shared by the UI and any derived export.
"""

from __future__ import annotations

import math
from numbers import Real
from typing import Dict, List, Mapping, Optional

from domain.simulation.measure.measure_metadata import measure_metadata_resolver
from domain.simulation.measure.measure_result import MeasureResult, MeasureStatus
from domain.simulation.models.display_metric import DisplayMetric
from domain.simulation.models.simulation_result import SimulationResult


_PREFIXABLE_UNITS = {"Hz", "s", "V", "A", "W", "Ω", "F", "H", "S"}
_ENGINEERING_SCALES = (
    (1e9, "G"),
    (1e6, "M"),
    (1e3, "k"),
    (1.0, ""),
    (1e-3, "m"),
    (1e-6, "μ"),
    (1e-9, "n"),
    (1e-12, "p"),
)


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
            metadata = measure_metadata_resolver.resolve(
                measure.name,
                statement=measure.statement,
            )
            target = resolved_targets.get(measure.name, "")
            if measure.status is MeasureStatus.OK and measure.is_valid:
                rows.append(
                    self._make_success_row(
                        name=measure.name,
                        value=measure.value,
                        unit=metadata.unit,
                        display_name=metadata.display_name,
                        target=target,
                    )
                )
                continue

            status = measure.status
            error_message = measure.error_message
            if status is MeasureStatus.OK:
                status = MeasureStatus.PARSE_ERROR
                error_message = (
                    error_message
                    or "Measurement result is not a finite numeric value"
                )
            rows.append(
                DisplayMetric(
                    name=measure.name,
                    display_name=metadata.display_name,
                    value="",
                    unit=metadata.unit,
                    status=status.value,
                    error_message=error_message,
                    raw_value=None,
                    target=target,
                )
            )
        return rows

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _make_success_row(
        self,
        *,
        name: str,
        value: object,
        unit: str,
        display_name: str,
        target: str,
    ) -> DisplayMetric:
        if isinstance(value, bool) or not isinstance(value, Real):
            raise TypeError("Successful measurement value must be numeric")
        raw_value = float(value)
        if not math.isfinite(raw_value):
            raise ValueError("Successful measurement value must be finite")

        return DisplayMetric(
            name=name,
            display_name=display_name,
            value=self._format_with_unit(raw_value, unit),
            unit=unit,
            status=MeasureStatus.OK.value,
            error_message="",
            raw_value=raw_value,
            target=target,
        )

    def _format_with_unit(self, value: float, unit: str) -> str:
        if not math.isfinite(value):
            return "N/A"
        normalized_unit = str(unit or "").strip()
        if normalized_unit not in _PREFIXABLE_UNITS:
            formatted = f"{value:.6g}"
            return f"{formatted} {normalized_unit}" if normalized_unit else formatted

        abs_value = abs(value)
        if abs_value == 0:
            return f"0 {normalized_unit}"
        for scale, prefix in _ENGINEERING_SCALES:
            scaled = abs_value / scale
            if 1 <= scaled < 1000:
                return f"{value / scale:.3g} {prefix}{normalized_unit}"
        return f"{value:.3e} {normalized_unit}"


display_metric_builder = DisplayMetricBuilder()


__all__ = ["DisplayMetricBuilder", "display_metric_builder"]
