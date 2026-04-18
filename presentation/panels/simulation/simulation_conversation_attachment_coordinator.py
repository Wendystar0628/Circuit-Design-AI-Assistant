from pathlib import Path
from typing import Any, List, Optional

from domain.simulation.data.simulation_artifact_exporter import simulation_artifact_exporter
from domain.simulation.models.simulation_result import SimulationResult
from shared.event_types import (
    EVENT_UI_ACTIVATE_CONVERSATION_TAB,
    EVENT_UI_ATTACH_FILES_TO_CONVERSATION,
)
from shared.service_locator import ServiceLocator
from shared.service_names import SVC_EVENT_BUS


class SimulationConversationAttachmentCoordinator:
    def __init__(self, chart_viewer, waveform_widget):
        self._chart_viewer = chart_viewer
        self._waveform_widget = waveform_widget
        self._event_bus = None

    @property
    def event_bus(self):
        if self._event_bus is None:
            self._event_bus = ServiceLocator.get_optional(SVC_EVENT_BUS)
        return self._event_bus

    def attach_metrics(
        self,
        project_root: str,
        export_root: Optional[str],
        result: SimulationResult,
        metrics: List[Any],
    ) -> str:
        """Ensure ``metrics.json`` exists for the current result and
        publish it to the conversation panel.

        The caller is responsible for building ``metrics`` from a
        ``DisplayMetric`` list whose ``target`` fields have already been
        populated by ``MetricTargetService``. We intentionally
        re-export on every call (even if a stale file already exists)
        so the agent never sees outdated target strings after the user
        tweaks them between simulation runs.
        """
        root = self._resolve_export_root(project_root, export_root, result)
        simulation_artifact_exporter.export_metrics(root, result, metrics)
        target_path = root / "metrics" / "metrics.json"
        self._ensure_file(target_path)
        self._publish([str(target_path)])
        return str(target_path)

    def attach_output_log(
        self,
        project_root: str,
        export_root: Optional[str],
        result: SimulationResult,
    ) -> str:
        root = self._resolve_export_root(project_root, export_root, result)
        target_path = root / "output_log" / "output_log.txt"
        if not target_path.is_file():
            simulation_artifact_exporter.export_output_log(root, result)
        self._ensure_file(target_path)
        self._publish([str(target_path)])
        return str(target_path)

    def attach_op_result(
        self,
        project_root: str,
        export_root: Optional[str],
        result: SimulationResult,
    ) -> str:
        root = self._resolve_export_root(project_root, export_root, result)
        text_path = root / "op_result" / "op_result.txt"
        json_path = root / "op_result" / "op_result.json"
        if not text_path.is_file() or not json_path.is_file():
            simulation_artifact_exporter.export_op_result(root, result)
        self._ensure_file(text_path)
        self._ensure_file(json_path)
        self._publish([str(text_path), str(json_path)])
        return str(json_path)

    def attach_chart_image(
        self,
        project_root: str,
        export_root: Optional[str],
        result: SimulationResult,
    ) -> str:
        root = self._resolve_export_root(project_root, export_root, result)
        target_dir = root / "charts"
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / "current_chart.png"
        if not self._chart_viewer.export_current_image(str(target_path)):
            raise ValueError("No chart image available for conversation attachment")
        self._ensure_file(target_path)
        self._publish([str(target_path)])
        return str(target_path)

    def attach_waveform_image(
        self,
        project_root: str,
        export_root: Optional[str],
        result: SimulationResult,
    ) -> str:
        root = self._resolve_export_root(project_root, export_root, result)
        target_dir = root / "waveforms"
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / "current_waveform.png"
        if not self._waveform_widget.export_image(str(target_path)):
            raise ValueError("No waveform image available for conversation attachment")
        self._ensure_file(target_path)
        self._publish([str(target_path)])
        return str(target_path)

    def _resolve_export_root(
        self,
        project_root: str,
        export_root: Optional[str],
        result: SimulationResult,
    ) -> Path:
        if export_root:
            path = Path(export_root)
            if path.exists():
                return path
        if not project_root:
            raise ValueError("Project export root is unavailable")
        return simulation_artifact_exporter.create_project_export_root(project_root, result)

    def _ensure_file(self, path: Path) -> None:
        if not path.is_file():
            raise FileNotFoundError(str(path))

    def _publish(self, paths: List[str]) -> None:
        if self.event_bus is None:
            raise RuntimeError("Event bus is unavailable")
        payload = {"paths": list(paths)}
        self.event_bus.publish(EVENT_UI_ATTACH_FILES_TO_CONVERSATION, payload)
        self.event_bus.publish(EVENT_UI_ACTIVATE_CONVERSATION_TAB, {})


__all__ = ["SimulationConversationAttachmentCoordinator"]
