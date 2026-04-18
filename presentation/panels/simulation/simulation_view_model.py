# Simulation ViewModel
"""
\u4eff\u771f\u9762\u677f ViewModel

\u804c\u8d23:
- \u4f5c\u4e3a UI \u4e0e\u4eff\u771f\u670d\u52a1\u4e4b\u95f4\u7684\u4e2d\u95f4\u5c42
- \u9694\u79bb simulation_tab \u4e0e SimulationService \u7684\u76f4\u63a5\u4f9d\u8d56
- \u8ba2\u9605\u4eff\u771f\u4e8b\u4ef6\u5e76\u8f6c\u6362\u4e3a UI \u53cb\u597d\u683c\u5f0f
- \u7ba1\u7406\u4eff\u771f\u72b6\u6001\u4e0e\u7ed3\u679c\u5c55\u793a\u3002\u5c06 .MEASURE \u7ed3\u679c\u7ffb\u8bd1\u4e3a
  DisplayMetric\uff0c\u5e76\u5728\u52a0\u8f7d\u65f6\u8bfb\u53d6 MetricTargetService \u5c06\u7528\u6237
  \u8bbe\u5b9a\u7684\u76ee\u6807\u503c\u7eb3\u5165\u3002

\u8bbe\u8ba1\u539f\u5219:
- DisplayMetric \u662f UI \u548c\u5bfc\u51fa\u7ba1\u7ebf\u5171\u4eab\u7684\u5c55\u793a\u6a21\u578b\uff0c
  \u5b57\u6bb5\u4ec5\u4fdd\u7559\u5b9e\u9645\u88ab\u6d88\u8d39\u7684\u6838\u5fc3\u9879\uff1a
  ``name`` / ``display_name`` / ``value`` / ``unit`` /
  ``raw_value`` / ``target``\u3002
- ViewModel \u4ec5\u8d1f\u8d23\u5c06 .MEASURE \u7ed3\u679c\u4e0e\u7528\u6237\u8bbe\u5b9a\u7684\u76ee\u6807
  \u503c\u5408\u5e76\u6210\u6307\u6807\u5217\u8868\uff0c\u4e0d\u627f\u62c5\u4efb\u4f55\u8bc4\u5206 / \u8fbe\u6807\u5224\u5b9a\u903b\u8f91\u3002
"""

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

from domain.simulation.measure.measure_metadata import measure_metadata_resolver
from domain.simulation.measure.measure_result import MeasureResult, MeasureStatus
from presentation.core.base_view_model import BaseViewModel
from domain.simulation.models.simulation_result import SimulationResult
from shared.event_types import (
    EVENT_SIM_STARTED,
    EVENT_SIM_COMPLETE,
    EVENT_SIM_ERROR,
)


class SimulationStatus(Enum):
    """\u4eff\u771f\u72b6\u6001\u679a\u4e3e"""

    IDLE = "idle"
    RUNNING = "running"
    COMPLETE = "complete"
    ERROR = "error"


@dataclass
class DisplayMetric:
    """UI \u53cb\u597d\u7684\u6307\u6807\u5c55\u793a\u683c\u5f0f\u3002

    \u4e0e ``MeasureResult`` \u7684\u5dee\u522b\uff1a``MeasureResult`` \u662f\u6267\u884c\u7ed3\u679c\uff0c
    ``DisplayMetric`` \u662f\u5df2\u683c\u5f0f\u5316\u3001\u9644\u5e26\u7528\u6237\u76ee\u6807\u503c\u7684\u5c55\u793a\u5c42\u89c6\u56fe
    \u3002\u5b57\u6bb5\u523b\u610f\u6536\u7a84\u5230\u771f\u6b63\u88ab\u4e0b\u6e38\uff08\u524d\u7aef\u8868\u683c\u3001JSON
    \u5bfc\u51fa\u3001Agent \u9644\u4ef6\uff09\u6d88\u8d39\u7684\u51e0\u4e2a\u5217\uff0c\u4ee5\u514d\u9057\u7559\u6b7b\u5bf9\u9f50\u3002
    """

    name: str
    """\u6307\u6807\u6807\u8bc6\u540d\uff08.MEASURE \u8bed\u53e5\u4e2d\u7684\u540d\u79f0\uff09\u3002"""

    display_name: str
    """\u5df2\u56fd\u9645\u5316\u7684\u5c55\u793a\u540d\u3002"""

    value: str
    """\u683c\u5f0f\u5316\u540e\u7684\u6570\u503c\u5b57\u7b26\u4e32\uff08\u5982 ``"20.5 dB"``\uff09\u3002"""

    unit: str
    """\u5355\u4f4d\uff08\u5982 ``dB`` / ``Hz`` / ``V``\uff09\u3002"""

    raw_value: Optional[float] = None
    """\u539f\u59cb\u6570\u503c\uff0c\u4f9b Agent / \u5bfc\u51fa\u7ba1\u7ebf\u7528\u4e8e\u8fd0\u7b97\u3002"""

    target: str = ""
    """\u7528\u6237\u8bbe\u5b9a\u7684\u76ee\u6807\u503c\u6587\u672c\uff08\u5982 ``"\u2265 20 dB"``\uff09\u3002
    \u7a7a\u5b57\u7b26\u4e32\u8868\u793a\u8be5\u6307\u6807\u672a\u8bbe\u5b9a\u76ee\u6807\u3002"""


class SimulationViewModel(BaseViewModel):
    """\u4eff\u771f\u9762\u677f ViewModel\u3002

    \u6838\u5fc3\u8f93\u51fa\uff1a``metrics_list``\uff08List[DisplayMetric]\uff09+
    ``current_result`` + ``simulation_status`` + ``error_message``\u3002
    \u8f93\u51fa\u901a\u8fc7 ``notify_property_changed`` \u63a8\u9001\u7ed9 SimulationTab\uff0c
    SimulationTab \u518d\u8c03\u7528 Serializer \u4ea7\u751f\u524d\u7aef\u72b6\u6001\u3002
    """

    def __init__(self):
        super().__init__()
        self._logger = logging.getLogger(__name__)

        self._current_result: Optional[SimulationResult] = None
        self._metrics_list: List[DisplayMetric] = []
        self._simulation_status: SimulationStatus = SimulationStatus.IDLE
        self._error_message: str = ""
        self._metric_target_service = None

    # ------------------------------------------------------------------
    # \u5c5e\u6027\u8bbf\u95ee\u5668
    # ------------------------------------------------------------------

    @property
    def current_result(self) -> Optional[SimulationResult]:
        return self._current_result

    @property
    def metrics_list(self) -> List[DisplayMetric]:
        return self._metrics_list

    @property
    def simulation_status(self) -> SimulationStatus:
        return self._simulation_status

    @property
    def error_message(self) -> str:
        return self._error_message

    @property
    def metric_target_service(self):
        if self._metric_target_service is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_METRIC_TARGET_SERVICE

                self._metric_target_service = ServiceLocator.get_optional(SVC_METRIC_TARGET_SERVICE)
            except Exception:
                self._metric_target_service = None
        return self._metric_target_service

    # ------------------------------------------------------------------
    # \u751f\u547d\u5468\u671f
    # ------------------------------------------------------------------

    def initialize(self):
        super().initialize()
        self.subscribe(EVENT_SIM_STARTED, self._on_simulation_started)
        self.subscribe(EVENT_SIM_COMPLETE, self._on_simulation_complete)
        self.subscribe(EVENT_SIM_ERROR, self._on_simulation_error)
        self._logger.info("SimulationViewModel initialized")

    # ------------------------------------------------------------------
    # \u4e8b\u4ef6\u5904\u7406
    # ------------------------------------------------------------------

    def _on_simulation_started(self, event_data: Dict[str, Any]):
        self._set_status(SimulationStatus.RUNNING)
        self._error_message = ""
        self.notify_property_changed("simulation_status", self._simulation_status)
        self.notify_property_changed("error_message", self._error_message)
        self._logger.info(
            f"Simulation started: {event_data.get('circuit_file', 'unknown')}"
        )

    def _on_simulation_complete(self, event_data: Dict[str, Any]):
        self._set_status(SimulationStatus.COMPLETE)
        self.notify_property_changed("simulation_status", self._simulation_status)
        self._logger.info("Simulation complete")

    def _on_simulation_error(self, event_data: Dict[str, Any]):
        self._set_status(SimulationStatus.ERROR)
        self._error_message = event_data.get("error_message", "Unknown error")
        self.notify_property_changed("simulation_status", self._simulation_status)
        self.notify_property_changed("error_message", self._error_message)
        self._logger.error(f"Simulation error: {self._error_message}")

    def _set_status(self, status: SimulationStatus):
        self._simulation_status = status

    # ------------------------------------------------------------------
    # \u6838\u5fc3\u65b9\u6cd5
    # ------------------------------------------------------------------

    def load_result(self, result: SimulationResult):
        """\u52a0\u8f7d\u4eff\u771f\u7ed3\u679c\u5e76\u8f6c\u6362\u4e3a\u5c55\u793a\u683c\u5f0f\u3002

        \u6bcf\u6b21\u52a0\u8f7d\u65f6\u4f1a\u91cd\u65b0\u67e5\u8be2 MetricTargetService\uff0c\u786e\u4fdd
        \u7528\u6237\u5bf9\u5f53\u524d\u7535\u8def\u6587\u4ef6\u7684\u6700\u65b0\u76ee\u6807\u503c\u4f1a\u540c\u6b65\u5230 UI\u3002\u4ec5\u5728
        ``result.success`` \u4e14 ``result.measurements`` \u6709\u503c\u65f6\u5c55\u793a\u6307\u6807\u3002
        """
        self._current_result = result

        if result.success and result.data is not None:
            measurements = result.measurements or []
            self._metrics_list = self._load_metrics_from_measurements(
                measurements,
                result.file_path,
            )
            self._set_status(SimulationStatus.COMPLETE)
            self._error_message = ""
        else:
            self._metrics_list = []
            self._set_status(SimulationStatus.ERROR)
            if result.error:
                if hasattr(result.error, "message"):
                    self._error_message = result.error.message
                else:
                    self._error_message = str(result.error)

        self.notify_properties_changed({
            "current_result": self._current_result,
            "metrics_list": self._metrics_list,
            "simulation_status": self._simulation_status,
            "error_message": self._error_message,
        })

    def refresh_metric_targets(self):
        """\u4ec5\u7528\u6237\u4fee\u6539\u76ee\u6807\u503c\u65f6\u8c03\u7528\uff0c\u5c06 MetricTargetService
        \u7684\u6700\u65b0\u6301\u4e45\u5316\u5185\u5bb9\u5408\u5e76\u56de\u5f53\u524d metrics_list \u5e76\u5e7f\u64ad\u3002
        \u56e0\u4e3a\u6309\u94ae\u786e\u8ba4\u540e\u4e0d\u4f1a\u89e6\u53d1\u4eff\u771f\u91cd\u8dd1\uff0c\u4ec5\u9700\u5237\u65b0
        target \u5b57\u6bb5\u3002"""
        if not self._metrics_list or self._current_result is None:
            return
        source_file = self._current_result.file_path or ""
        targets = self._resolve_targets(source_file)
        updated = [
            DisplayMetric(
                name=metric.name,
                display_name=metric.display_name,
                value=metric.value,
                unit=metric.unit,
                raw_value=metric.raw_value,
                target=targets.get(metric.name, ""),
            )
            for metric in self._metrics_list
        ]
        self._metrics_list = updated
        self.notify_property_changed("metrics_list", self._metrics_list)

    def _load_metrics_from_measurements(
        self,
        measurements: List[Any],
        source_file_path: str,
    ) -> List[DisplayMetric]:
        targets = self._resolve_targets(source_file_path)
        display_metrics: List[DisplayMetric] = []

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
            display_metrics.append(
                self._build_display_metric(
                    name=measure.name,
                    value=measure.value,
                    unit=metadata.unit,
                    display_name=display_name,
                    target=targets.get(measure.name, ""),
                )
            )
        return display_metrics

    def _build_display_metric(
        self,
        *,
        name: str,
        value: Any,
        unit: str,
        display_name: str,
        target: str,
    ) -> DisplayMetric:
        raw_value: Optional[float] = None
        formatted_value: str = str(value) if value is not None else "N/A"

        if isinstance(value, (int, float)):
            raw_value = float(value)
            formatted_value = self._format_value_with_unit(raw_value, unit)
        elif isinstance(value, str):
            import re

            match = re.match(r"^([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)\s*(.*)$", value.strip())
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

    def _format_value_with_unit(self, value: float, unit: str) -> str:
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

    def _resolve_targets(self, source_file_path: str) -> Dict[str, str]:
        service = self.metric_target_service
        if service is None or not source_file_path:
            return {}
        try:
            return service.get_targets_for_file(source_file_path)
        except Exception:
            return {}

    # ------------------------------------------------------------------
    # \u8f85\u52a9\u65b9\u6cd5
    # ------------------------------------------------------------------

    def get_metric_by_name(self, name: str) -> Optional[DisplayMetric]:
        for metric in self._metrics_list:
            if metric.name == name:
                return metric
        return None

    def clear(self):
        self._current_result = None
        self._metrics_list = []
        self._simulation_status = SimulationStatus.IDLE
        self._error_message = ""
        self.notify_properties_changed({
            "current_result": None,
            "metrics_list": [],
            "simulation_status": SimulationStatus.IDLE,
            "error_message": "",
        })


__all__ = [
    "SimulationViewModel",
    "SimulationStatus",
    "DisplayMetric",
]
