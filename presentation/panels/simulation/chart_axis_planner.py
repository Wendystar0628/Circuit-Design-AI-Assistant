from dataclasses import dataclass, replace
from typing import Dict, Iterable, List, Optional, Sequence, Set

from presentation.panels.simulation.chart_view_types import ChartSeries


@dataclass(frozen=True)
class ChartAxisDescriptor:
    label: str
    log_enabled: bool = False


@dataclass(frozen=True)
class ChartAxisPlan:
    left_axis: ChartAxisDescriptor
    right_axis: Optional[ChartAxisDescriptor]
    series_axis_keys: Dict[str, str]


_FAMILY_LABELS: Dict[str, str] = {
    "voltage": "Voltage (V)",
    "current": "Current (A)",
    "other": "Signal Value",
    "noise_voltage_density": "Voltage Noise Density (V/√Hz)",
    "noise_current_density": "Current Noise Density (A/√Hz)",
    "noise_other_density": "Noise Spectral Density",
    "magnitude_db": "Magnitude (dB)",
    "phase_deg": "Phase (°)",
}

_FAMILY_PRIORITY: Dict[str, int] = {
    "voltage": 0,
    "noise_voltage_density": 0,
    "magnitude_db": 0,
    "current": 1,
    "noise_current_density": 1,
    "phase_deg": 1,
    "other": 2,
    "noise_other_density": 2,
}

_FAMILY_LOG_ENABLED: Dict[str, bool] = {
    "voltage": False,
    "current": False,
    "other": False,
    "noise_voltage_density": True,
    "noise_current_density": True,
    "noise_other_density": True,
    "magnitude_db": False,
    "phase_deg": False,
}

_DEFAULT_FAMILY = "other"
_DEFAULT_AXIS_LABEL = _FAMILY_LABELS[_DEFAULT_FAMILY]


def build_chart_axis_plan(
    series_list: Sequence[ChartSeries],
    visible_series_names: Optional[Iterable[str]] = None,
) -> ChartAxisPlan:
    normalized_series = [series for series in series_list if isinstance(series, ChartSeries)]
    if not normalized_series:
        return ChartAxisPlan(
            left_axis=ChartAxisDescriptor(label=_DEFAULT_AXIS_LABEL, log_enabled=False),
            right_axis=None,
            series_axis_keys={},
        )

    visible_names = {
        str(name or "")
        for name in visible_series_names or []
        if str(name or "")
    }
    active_series = [series for series in normalized_series if series.name in visible_names] if visible_names else list(normalized_series)
    if not active_series:
        active_series = list(normalized_series)

    ordered_families = _ordered_families(active_series)
    primary_family = ordered_families[0] if ordered_families else _DEFAULT_FAMILY
    secondary_family = ordered_families[1] if len(ordered_families) > 1 else None

    left_families: Set[str] = {primary_family}
    right_families: Set[str] = {secondary_family} if secondary_family else set()
    for family in ordered_families[2:]:
        left_families.add(family)

    series_axis_keys = {
        series.name: "right" if _normalize_family(series.axis_family) in right_families else "left"
        for series in normalized_series
    }

    return ChartAxisPlan(
        left_axis=ChartAxisDescriptor(
            label=_compose_axis_label(left_families),
            log_enabled=_axis_log_enabled(left_families),
        ),
        right_axis=(
            ChartAxisDescriptor(
                label=_compose_axis_label(right_families),
                log_enabled=_axis_log_enabled(right_families),
            )
            if right_families
            else None
        ),
        series_axis_keys=series_axis_keys,
    )


def apply_axis_plan(series_list: Sequence[ChartSeries], plan: ChartAxisPlan) -> List[ChartSeries]:
    applied: List[ChartSeries] = []
    for series in series_list:
        axis_key = plan.series_axis_keys.get(series.name, "left")
        applied.append(replace(series, axis_key=axis_key))
    return applied


def resolve_axis_key(series: ChartSeries, plan: ChartAxisPlan) -> str:
    return plan.series_axis_keys.get(series.name, "left")


def resolve_axis_label(series: ChartSeries, plan: ChartAxisPlan) -> str:
    axis_key = resolve_axis_key(series, plan)
    if axis_key == "right" and plan.right_axis is not None:
        return plan.right_axis.label
    return plan.left_axis.label


def resolve_axis_log_enabled(series: ChartSeries, plan: ChartAxisPlan) -> bool:
    axis_key = resolve_axis_key(series, plan)
    if axis_key == "right" and plan.right_axis is not None:
        return plan.right_axis.log_enabled
    return plan.left_axis.log_enabled


def _ordered_families(series_list: Sequence[ChartSeries]) -> List[str]:
    families = {_normalize_family(series.axis_family) for series in series_list}
    return sorted(
        families,
        key=lambda family: (_FAMILY_PRIORITY.get(family, 99), _FAMILY_LABELS.get(family, _DEFAULT_AXIS_LABEL)),
    )


def _normalize_family(value: str) -> str:
    candidate = str(value or "").strip().lower()
    if candidate in _FAMILY_LABELS:
        return candidate
    return _DEFAULT_FAMILY


def _compose_axis_label(families: Iterable[str]) -> str:
    ordered = sorted(
        {_normalize_family(family) for family in families},
        key=lambda family: (_FAMILY_PRIORITY.get(family, 99), _FAMILY_LABELS.get(family, _DEFAULT_AXIS_LABEL)),
    )
    if not ordered:
        return _DEFAULT_AXIS_LABEL
    if len(ordered) == 1:
        return _FAMILY_LABELS.get(ordered[0], _DEFAULT_AXIS_LABEL)
    return " / ".join(_FAMILY_LABELS.get(family, _DEFAULT_AXIS_LABEL) for family in ordered)


def _axis_log_enabled(families: Iterable[str]) -> bool:
    normalized = {_normalize_family(family) for family in families}
    return any(_FAMILY_LOG_ENABLED.get(family, False) for family in normalized)


__all__ = [
    "ChartAxisDescriptor",
    "ChartAxisPlan",
    "apply_axis_plan",
    "build_chart_axis_plan",
    "resolve_axis_key",
    "resolve_axis_label",
    "resolve_axis_log_enabled",
]
